package storage

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func mappingFixture(t *testing.T) (string, map[string]any) {
	t.Helper()
	root := t.TempDir()
	path := filepath.Join(root, "test.bme")
	data := []byte("#TITLE Fixture\n#BPM 120\n#WAV01 shared.wav\n#00101:01\n#00101:01\n")
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(data)
	events := []any{}
	for i := 0; i < 2; i++ {
		events = append(events, map[string]any{"source_index": i, "bms_tick": 384, "original_tick": 0, "bms_channel": "01", "wav_id": "01",
			"source_note": map[string]any{"track_id": 7 + i, "track_name": "Track", "channel_id": 10, "channel_name": "Piano", "key_id": "key", "key": 60}})
	}
	mapping := map[string]any{"schema_version": 2, "chart_sha256": hex.EncodeToString(hash[:]), "ppq": 96, "source": map[string]any{"file": "fixture.flp"},
		"definitions": []any{map[string]any{"wav_id": "01", "file": "shared.wav", "key_id": "key"}}, "events": events}
	return path, mapping
}
func writeMapping(t *testing.T, path string, v any) {
	t.Helper()
	data, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(filepath.Dir(path), "mapping.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestDawMappingSharedSoundSaveAsAndReopen(t *testing.T) {
	path, mapping := mappingFixture(t)
	writeMapping(t, path, mapping)
	d, err := Read(path, "Auto")
	if err != nil {
		t.Fatal(err)
	}
	if d.DawDraft == nil || d.Notes[0].DawOrigin.TrackID != 7 || d.Notes[1].DawOrigin.TrackID != 8 {
		t.Fatalf("sources not attached: %+v", d)
	}
	d.Notes[0].Channel = 37
	newPath := filepath.Join(t.TempDir(), "edited.bme")
	next, err := Rebase(d, newPath)
	if err != nil {
		t.Fatal(err)
	}
	if err = Save(next, newPath); err != nil {
		t.Fatal(err)
	}
	reopened, err := Read(newPath, "Auto")
	if err != nil {
		t.Fatal(err)
	}
	if reopened.DawDraft == nil || len(reopened.Notes) != 2 {
		t.Fatal("saved sources lost")
	}
	for _, n := range reopened.Notes {
		if n.DawOrigin == nil {
			t.Fatal("source lost")
		}
		if n.Channel == 37 && n.DawOrigin.TrackID != 7 {
			t.Fatal("role change changed source")
		}
	}
}

func TestDawMappingRejectsMismatchAtomically(t *testing.T) {
	for _, kind := range []string{"hash", "late_event", "wav", "missing_source"} {
		t.Run(kind, func(t *testing.T) {
			path, mapping := mappingFixture(t)
			event := mapping["events"].([]any)[1].(map[string]any)
			switch kind {
			case "hash":
				mapping["chart_sha256"] = "wrong"
			case "late_event":
				event["bms_tick"] = 400
			case "wav":
				mapping["definitions"].([]any)[0].(map[string]any)["file"] = "different.wav"
			case "missing_source":
				delete(event["source_note"].(map[string]any), "track_id")
			}
			writeMapping(t, path, mapping)
			d, err := Read(path, "Auto")
			if err != nil {
				t.Fatal(err)
			}
			if d.DawDraft != nil || len(d.Warnings) == 0 || len(d.Notes) != 2 {
				t.Fatal("invalid metadata accepted")
			}
			for _, n := range d.Notes {
				if n.DawOrigin != nil {
					t.Fatal("partial metadata attached")
				}
			}
		})
	}
}

func TestLegacyDawMappingUsesExportReport(t *testing.T) {
	path, mapping := mappingFixture(t)
	report := map[string]any{"chart_sha256": mapping["chart_sha256"], "ppq": mapping["ppq"], "source": mapping["source"]}
	delete(mapping, "schema_version")
	delete(mapping, "chart_sha256")
	delete(mapping, "ppq")
	delete(mapping, "source")
	writeMapping(t, path, mapping)
	b, _ := json.Marshal(report)
	if err := os.WriteFile(filepath.Join(filepath.Dir(path), "export_report.json"), b, 0600); err != nil {
		t.Fatal(err)
	}
	d, err := Read(path, "Auto")
	if err != nil || d.DawDraft == nil {
		t.Fatalf("legacy import failed: %v %+v", err, d.Warnings)
	}
}

func TestDawDraftLocalConversion(t *testing.T) {
	path := os.Getenv("DAW2BMS_TEST_CHART")
	if path == "" {
		t.Skip("Set DAW2BMS_TEST_CHART to validate a local conversion")
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	d, err := Read(path, "Auto")
	if err != nil {
		t.Fatal(err)
	}
	if d.DawDraft == nil || len(d.Notes) == 0 {
		t.Fatalf("conversion has no mapped draft: %+v", d.Warnings)
	}
	for _, n := range d.Notes {
		if n.DawOrigin == nil || n.DawOrigin.InstrumentName == "" {
			t.Fatal("audio event has no source instrument")
		}
	}
	savedPath := filepath.Join(t.TempDir(), "draft-edited.bme")
	next, err := Rebase(d, savedPath)
	if err != nil {
		t.Fatal(err)
	}
	if err = Save(next, savedPath); err != nil {
		t.Fatal(err)
	}
	back, err := Read(savedPath, "Auto")
	if err != nil {
		t.Fatal(err)
	}
	if back.DawDraft == nil || len(back.Notes) != len(d.Notes) {
		t.Fatal("source data lost on save")
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(before) != string(after) {
		t.Fatal("local source chart changed")
	}
}
