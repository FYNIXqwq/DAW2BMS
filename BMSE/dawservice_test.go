package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestDawHelperProcess(t *testing.T) {
	if os.Getenv("BMSE_DAW_TEST_HELPER") != "1" {
		return
	}
	reader := bufio.NewReader(os.Stdin)
	line, _ := reader.ReadBytes('\n')
	var request map[string]json.RawMessage
	if json.Unmarshal(line, &request) != nil {
		os.Exit(3)
	}
	var action, source, out string
	_ = json.Unmarshal(request["action"], &action)
	_ = json.Unmarshal(request["source"], &source)
	_ = json.Unmarshal(request["out"], &out)
	emit := func(v any) { _ = json.NewEncoder(os.Stdout).Encode(v) }
	emit(map[string]any{"type": "hello", "protocol": 1})
	b, _ := os.ReadFile(source)
	hash := sha256.Sum256(b)
	if action == "inspect" {
		emit(map[string]any{"type": "tracks", "data": DawPreview{Path: source, SHA256: hex.EncodeToString(hash[:]), DAW: "fl_studio", Arrangements: []DawArrangement{{ID: 0, Name: "Arrangement", Tracks: []DawTrack{{ID: 1, Name: "主旋律", Notes: 1, Supported: true}, {ID: 2, Name: "伴奏", Notes: 1, Supported: true}}}}}})
		os.Exit(0)
	}
	if string(b) == "crash" {
		fmt.Fprintln(os.Stderr, "simulated engine failure")
		os.Exit(2)
	}
	_ = os.MkdirAll(filepath.Join(out, "chart", "audio"), 0700)
	_ = os.WriteFile(filepath.Join(out, "request.json"), line, 0600)
	emit(map[string]any{"type": "progress", "stage": 2, "message": "rendering", "level": "info"})
	if string(b) == "wait" {
		line, _ = reader.ReadBytes('\n')
		if !strings.Contains(string(line), "cancel") {
			os.Exit(4)
		}
		emit(map[string]any{"type": "cancelled", "message": "cancelled", "data": DawResult{Status: "cancelled", OutputDirectory: out}})
		os.Exit(0)
	}
	_ = os.WriteFile(filepath.Join(out, "chart", "test.bme"), []byte("#TITLE DAW imported\n#BPM 120\n#WAV01 audio/key.wav\n#00111:01\n#00101:01\n"), 0600)
	_ = os.WriteFile(filepath.Join(out, "chart", "audio", "key.wav"), []byte("test audio"), 0600)
	chartPath := "chart/test.bme"
	if string(b) == "escape" {
		chartPath = "../outside.bme"
	}
	emit(map[string]any{"type": "result", "data": DawResult{Status: "complete", OutputDirectory: out, Chart: chartPath, AudioComplete: true, PlayableNotes: 1, BGMEvents: 1}})
	os.Exit(0)
}
func dawTestEditor(t *testing.T) (*EditorService, string, DawRequest) {
	t.Helper()
	dir := t.TempDir()
	source := filepath.Join(dir, "工程 ; & 日本語.als")
	if e := os.WriteFile(source, []byte("fixture"), 0600); e != nil {
		t.Fatal(e)
	}
	s := &EditorService{configDir: dir, settings: Settings{UI: map[string]any{}}, dawCommand: func(ctx context.Context, cfg DawConfig) *exec.Cmd {
		cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestDawHelperProcess$")
		cmd.Env = append(os.Environ(), "BMSE_DAW_TEST_HELPER=1")
		return cmd
	}}
	if e := s.DawSaveSettings(DawConfig{Python: os.Args[0], Language: "en"}); e != nil {
		t.Fatal(e)
	}
	p, e := s.DawInspect(source, "en")
	if e != nil {
		t.Fatal(e)
	}
	r := DawRequest{Source: source, SourceHash: p.SHA256, OutputParent: filepath.Join(dir, "output"), Language: "en", PlayTracks: []int{1}, ExcludeTracks: []int{}, InitialTail: 1, MaxTail: 30, MaxAttempts: 5, ThresholdDB: -60, Timeout: 10, LeadInBars: 1, Deduplicate: true}
	return s, source, r
}
func awaitDaw(t *testing.T, s *EditorService) *DawJob {
	t.Helper()
	until := time.Now().Add(8 * time.Second)
	for time.Now().Before(until) {
		j := s.DawStatus()
		if j != nil && j.Status != "running" && s.diskOperations.Load() == 0 {
			return j
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("job did not finish")
	return nil
}
func TestDawImportOpensGeneratedChartWithRelativeAssets(t *testing.T) {
	s, source, request := dawTestEditor(t)
	before, _ := os.ReadFile(source)
	job, e := s.DawStart(request)
	if e != nil {
		t.Fatal(e)
	}
	result := awaitDaw(t, s)
	if result.Status != "complete" {
		t.Fatal(result.Error)
	}
	d, e := s.DawOpenResult(job.ID)
	if e != nil {
		t.Fatal(e)
	}
	if d.Path != filepath.Join(job.OutputDir, "chart", "test.bme") || len(d.Notes) != 2 {
		t.Fatalf("bad imported chart: %#v", d)
	}
	if _, e = os.Stat(filepath.Join(filepath.Dir(d.Path), "audio", "key.wav")); e != nil {
		t.Fatal(e)
	}
	after, _ := os.ReadFile(source)
	if string(before) != string(after) {
		t.Fatal("source mutated")
	}
	var received struct {
		Options map[string]json.RawMessage `json:"options"`
	}
	b, _ := os.ReadFile(filepath.Join(job.OutputDir, "request.json"))
	_ = json.Unmarshal(b, &received)
	if string(received.Options["play_tracks"]) != "[1]" || string(received.Options["exclude_tracks"]) != "[]" {
		t.Fatal("role selection not forwarded")
	}
	second, e := s.DawStart(request)
	if e != nil {
		t.Fatal(e)
	}
	if second.OutputDir == job.OutputDir {
		t.Fatal("output reused")
	}
	awaitDaw(t, s)
}
func TestDawCancellationAndCloseGuard(t *testing.T) {
	s, source, request := dawTestEditor(t)
	_ = os.WriteFile(source, []byte("wait"), 0600)
	j, e := s.DawStart(request)
	if e != nil {
		t.Fatal(e)
	}
	if s.diskOperations.Load() == 0 {
		t.Fatal("closing is not guarded")
	}
	if _, e = s.DawStart(request); e == nil {
		t.Fatal("allowed concurrent conversion")
	}
	if _, e = s.DawInspect(source, "en"); e == nil {
		t.Fatal("allowed concurrent inspection")
	}
	if e = s.DawCancel(j.ID); e != nil {
		t.Fatal(e)
	}
	_ = s.DawCancel(j.ID)
	if got := awaitDaw(t, s); got.Status != "cancelled" {
		t.Fatalf("%+v", got)
	}
	if _, e = s.DawOpenResult(j.ID); e == nil {
		t.Fatal("opened cancelled job")
	}
}
func TestDawFailuresAndEscapingResultsAreNotOpened(t *testing.T) {
	for _, content := range []string{"crash", "escape"} {
		t.Run(content, func(t *testing.T) {
			s, source, r := dawTestEditor(t)
			_ = os.WriteFile(source, []byte(content), 0600)
			job, e := s.DawStart(r)
			if e != nil {
				t.Fatal(e)
			}
			got := awaitDaw(t, s)
			if got.Status != "error" || got.Error == "" {
				t.Fatalf("%+v", got)
			}
			if _, e = s.DawOpenResult(job.ID); e == nil {
				t.Fatal("opened failed result")
			}
		})
	}
}
func TestDawProtocolRejectsTruncatedAndForeignOutput(t *testing.T) {
	for _, input := range []string{"noise\n", "{\"type\":\"hello\",\"protocol\":99}\n", "{\"type\":\"hello\",\"protocol\":1}\n"} {
		if e := consumeDaw(strings.NewReader(input), func(dawEvent) error { return nil }); e == nil {
			t.Fatal("accepted incomplete protocol")
		}
	}
	for _, path := range []string{"../escape.bme", "C:/absolute.bme", "."} {
		if _, e := dawResultPath(t.TempDir(), path); e == nil {
			t.Fatalf("accepted %q", path)
		}
	}
}
