package storage

import (
	"bmse/internal/chart"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type mappingSource struct {
	File string `json:"file"`
	Hash string `json:"sha256"`
}
type dawMapping struct {
	Version     int           `json:"schema_version"`
	ChartHash   string        `json:"chart_sha256"`
	PPQ         int           `json:"ppq"`
	Source      mappingSource `json:"source"`
	Arrangement int           `json:"arrangement_id"`
	Definitions []struct {
		ID    string `json:"wav_id"`
		File  string `json:"file"`
		KeyID string `json:"key_id"`
	} `json:"definitions"`
	Events []struct {
		Index    int    `json:"source_index"`
		Tick     int64  `json:"bms_tick"`
		Original int64  `json:"original_tick"`
		Channel  string `json:"bms_channel"`
		WAV      string `json:"wav_id"`
		Note     struct {
			TrackID        *int   `json:"track_id"`
			TrackName      string `json:"track_name"`
			ChannelID      *int   `json:"channel_id"`
			ChannelName    string `json:"channel_name"`
			InstrumentName string `json:"instrument_name"`
			KeyID          string `json:"key_id"`
			Pitch          int    `json:"key"`
			Arrangement    int    `json:"arrangement_id"`
		} `json:"source_note"`
	} `json:"events"`
}

func readMappingJSON(path string, target any) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, (64<<20)+1))
	if err != nil {
		return err
	}
	if len(b) > 64<<20 {
		return fmt.Errorf("mapping exceeds 64 MiB")
	}
	return json.Unmarshal(b, target)
}

func mappingKey(tick int64, channel, value int) string {
	if channel >= chart.BGMLane {
		channel = 1
	}
	return fmt.Sprintf("%d/%d/%d", tick, channel, value)
}

// Attach a source to each occurrence, not each WAV: one sample may be shared by
// different DAW tracks. Nothing is attached unless the entire mapping validates.
func attachDawMapping(d *chart.Document, mapping dawMapping) error {
	if mapping.Version != 0 && mapping.Version != 1 && mapping.Version != 2 {
		return fmt.Errorf("unsupported mapping version")
	}
	if mapping.PPQ <= 0 || mapping.PPQ > 1000000 || len(mapping.Events) > 200000 || d.SourceText != "" {
		return fmt.Errorf("unsupported mapping timing or chart")
	}
	definitions := map[int]string{}
	for _, def := range mapping.Definitions {
		id, err := chart.DecodeID(def.ID, 36)
		if err != nil || id == 0 {
			return fmt.Errorf("invalid mapping WAV")
		}
		if _, exists := definitions[id]; exists {
			return fmt.Errorf("duplicate mapping WAV")
		}
		if strings.ReplaceAll(d.WAV[strconv.Itoa(id)], "\\", "/") != strings.ReplaceAll(def.File, "\\", "/") {
			return fmt.Errorf("mapping WAV filename mismatch")
		}
		definitions[id] = def.KeyID
	}
	indices := map[string][]int{}
	count := 0
	bar := int64(mapping.PPQ) * 4
	for _, ratio := range d.Measures {
		if ratio != 1 {
			return fmt.Errorf("mapping requires 4/4 measures")
		}
	}
	for i, n := range d.Notes {
		if !(chart.KeyChannel(n.Channel) || n.Channel >= chart.BGMLane) {
			continue
		}
		if n.Kind != "normal" || n.Denominator <= 0 || (int64(n.Numerator)*bar)%int64(n.Denominator) != 0 {
			return fmt.Errorf("mapping note timing mismatch")
		}
		tick := int64(n.Measure)*bar + int64(n.Numerator)*bar/int64(n.Denominator)
		key := mappingKey(tick, n.Channel, int(n.Value))
		indices[key] = append(indices[key], i)
		count++
	}
	if count != len(mapping.Events) {
		return fmt.Errorf("mapping event count mismatch")
	}
	origins := map[int]chart.DawOrigin{}
	for _, event := range mapping.Events {
		id, err := chart.DecodeID(event.WAV, 36)
		if err != nil {
			return err
		}
		channel, err := chart.DecodeID(event.Channel, 36)
		if err != nil {
			return err
		}
		if event.Tick < 0 || (channel != 1 && !chart.KeyChannel(channel)) || event.Note.TrackID == nil || event.Note.ChannelID == nil || *event.Note.TrackID < 0 || *event.Note.ChannelID < 0 {
			return fmt.Errorf("missing or invalid source identity")
		}
		if key, ok := definitions[id]; !ok || key != event.Note.KeyID {
			return fmt.Errorf("mapping keysound mismatch")
		}
		key := mappingKey(event.Tick, channel, id)
		bucket := indices[key]
		if len(bucket) == 0 {
			return fmt.Errorf("mapping event not found")
		}
		instrument := event.Note.InstrumentName
		if instrument == "" {
			instrument = event.Note.ChannelName
		}
		origins[bucket[0]] = chart.DawOrigin{TrackID: *event.Note.TrackID, TrackName: event.Note.TrackName,
			ChannelID: *event.Note.ChannelID, InstrumentName: instrument, KeyID: event.Note.KeyID, Pitch: event.Note.Pitch,
			SourceIndex: event.Index, OriginalTick: event.Original}
		indices[key] = bucket[1:]
	}
	for i, origin := range origins {
		v := origin
		d.Notes[i].DawOrigin = &v
	}
	daw := "fl_studio"
	if strings.EqualFold(filepath.Ext(mapping.Source.File), ".als") {
		daw = "ableton_live"
	}
	d.DawDraft = &chart.DawDraft{Version: 1, SourceFile: filepath.Base(mapping.Source.File), SourceHash: mapping.Source.Hash,
		DAW: daw, PPQ: mapping.PPQ, ArrangementID: mapping.Arrangement}
	return nil
}

func loadDawMapping(d *chart.Document, original []byte) error {
	var mapping dawMapping
	err := readMappingJSON(filepath.Join(filepath.Dir(d.Path), "mapping.json"), &mapping)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	// Legacy packages keep hash and PPQ in export_report.json.
	if mapping.Version < 2 {
		var report struct {
			Hash   string        `json:"chart_sha256"`
			PPQ    int           `json:"ppq"`
			Source mappingSource `json:"source"`
		}
		if err := readMappingJSON(filepath.Join(filepath.Dir(d.Path), "export_report.json"), &report); err != nil {
			return err
		}
		mapping.ChartHash, mapping.PPQ, mapping.Source = report.Hash, report.PPQ, report.Source
		if len(mapping.Events) > 0 {
			mapping.Arrangement = mapping.Events[0].Note.Arrangement
		}
	}
	hash := sha256.Sum256(original)
	if mapping.ChartHash != hex.EncodeToString(hash[:]) {
		return fmt.Errorf("mapping belongs to another or modified chart")
	}
	return attachDawMapping(d, mapping)
}
