package main

import (
	"bmse/internal/chart"
	"bmse/internal/storage"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fakeDialogs struct {
	open, save string
	err        error
	saveName   string
}

func (f *fakeDialogs) OpenChart() (string, error)             { return f.open, f.err }
func (f *fakeDialogs) SaveChart(name string) (string, error)  { f.saveName = name; return f.save, f.err }
func (f *fakeDialogs) PickViewer() (string, error)            { return f.open, f.err }
func (f *fakeDialogs) PickMaterials(string) ([]string, error) { return []string{f.open}, f.err }
func service(t *testing.T) *EditorService {
	t.Helper()
	t.Setenv("BMSE_CONFIG_DIR", t.TempDir())
	return newEditor()
}
func TestDialogCancellationAndSaveAs(t *testing.T) {
	s := service(t)
	fake := &fakeDialogs{}
	s.dialogs = fake
	if d, e := s.Open("", "Auto"); e != nil || d != nil {
		t.Fatalf("cancelled open changed document %v", e)
	}
	d := chart.New()
	if path, e := s.Save(d, true); e != nil || path != "" {
		t.Fatal("cancelled save was not a no-op")
	}
	fake.save = filepath.Join(t.TempDir(), "new chart.bms")
	if _, e := s.Save(d, true); e != nil {
		t.Fatal(e)
	}
	if _, e := storage.Read(fake.save, "Auto"); e != nil {
		t.Fatal(e)
	}
	d.Path = filepath.Join(filepath.Dir(fake.save), "import.ibmsc")
	if _, e := s.Save(d, false); e != nil {
		t.Fatal(e)
	}
	if !strings.HasSuffix(fake.saveName, ".bms") {
		t.Fatal("binary project would be overwritten")
	}
	fake.err = errors.New("dialog failed")
	if _, e := s.Open("", "Auto"); e == nil {
		t.Fatal("dialog error swallowed")
	}
}
func TestViewerProfilesPersist(t *testing.T) {
	s := service(t)
	settings := s.Settings()
	settings.Viewers = []Viewer{{Name: "first", Path: "first.exe"}, {Name: "second", Path: "second.exe", PlayArgs: []string{"<measure>", "<filename>"}}}
	settings.SelectedViewer = 1
	if e := s.SaveSettings(settings); e != nil {
		t.Fatal(e)
	}
	loaded := newEditor().Settings()
	if loaded.Viewer != "second.exe" || len(loaded.Viewers) != 2 {
		t.Fatal("selected viewer not persisted")
	}
}

func TestReadLegacyBundle(t *testing.T) {
	s := service(t)
	dir := t.TempDir()
	_ = os.Mkdir(filepath.Join(dir, "theme"), 0700)
	_ = os.Mkdir(filepath.Join(dir, "lang"), 0700)
	for file, text := range map[string]string{"bmse.ini": "[Main]\nKey=BMSE\nTheme=custom.ini", "shortcut.ini": "[SP]\nSC=A", "theme/custom.ini": "[Main]\nKey=BMSE\nBackground=1,2,3", "lang/custom.ini": "[Main]\nKey=BMSE\nLanguage=Test"} {
		if e := os.WriteFile(filepath.Join(dir, file), []byte(text), 0600); e != nil {
			t.Fatal(e)
		}
	}
	bundle, e := s.ReadLegacy(filepath.Join(dir, "bmse.ini"))
	if e != nil {
		t.Fatal(e)
	}
	if bundle["baseDirectory"] != dir || bundle["theme/custom.ini"] == "" || bundle["shortcut.ini"] == "" {
		t.Fatal("incomplete legacy bundle", bundle)
	}
}

func TestDiskOperationGateIsReleasedOnErrors(t *testing.T) {
	s := service(t)
	if _, e := s.ApplyAssets("expired"); e == nil {
		t.Fatal("missing expired token error")
	}
	if s.diskOperations.Load() != 0 {
		t.Fatal("operation lock leaked")
	}
	if _, e := s.RestoreAssets(filepath.Join(t.TempDir(), "bad.json")); e == nil {
		t.Fatal("invalid journal accepted")
	}
	if s.diskOperations.Load() != 0 {
		t.Fatal("restore lock leaked")
	}
	s.diskOperations.Add(1)
	s.Quit()
	if s.diskOperations.Load() != 1 {
		t.Fatal("quit changed in-progress operation")
	}
}

func TestAuditRecoveryRevisionsRejectLateWrites(t *testing.T) {
	s := service(t)
	old := chart.New()
	old.Headers["TITLE"] = "old"
	if e := s.BackupVersioned(old, 10); e != nil {
		t.Fatal(e)
	}
	if e := s.ClearRecoveryVersioned(20); e != nil {
		t.Fatal(e)
	}
	if e := s.BackupVersioned(old, 15); e != nil {
		t.Fatal(e)
	}
	if d, e := s.Recovery(); e != nil || d != nil {
		t.Fatal("stale backup resurrected", d, e)
	}
	current := chart.New()
	current.Headers["TITLE"] = "current"
	if e := s.BackupVersioned(current, 30); e != nil {
		t.Fatal(e)
	}
	if e := s.ClearRecoveryVersioned(25); e != nil {
		t.Fatal(e)
	}
	if d, e := s.Recovery(); e != nil || d.Headers["TITLE"] != "current" {
		t.Fatal("stale clear removed current recovery", d, e)
	}
}
func TestAuditSaveAsReturnsRebasedDocument(t *testing.T) {
	s := service(t)
	oldDir, newDir := t.TempDir(), t.TempDir()
	d := chart.New()
	d.Path = filepath.Join(oldDir, "a.bms")
	d.WAV["1"] = "sound.wav"
	target := filepath.Join(newDir, "b.bms")
	s.dialogs = &fakeDialogs{save: target}
	r, e := s.SaveDocument(d, true)
	if e != nil {
		t.Fatal(e)
	}
	if filepath.Clean(filepath.Join(newDir, r.WAV["1"])) != filepath.Join(oldDir, "sound.wav") {
		t.Fatal(r.WAV)
	}
	saved, e := storage.Read(target, "Auto")
	if e != nil || saved.WAV["1"] != r.WAV["1"] {
		t.Fatal("UI document does not match saved file", e)
	}
	if d.WAV["1"] != "sound.wav" {
		t.Fatal("caller mutated")
	}
}

func TestAuditCorruptSettingsAndStaleHistoryWrites(t *testing.T) {
	s := service(t)
	path := filepath.Join(s.configDir, "settings.json")
	for _, data := range []string{`{"ui":null,"recent":null,"viewers":[{}],"selectedViewer":99}`, `{"viewer":123,"ui":null}`} {
		if e := os.WriteFile(path, []byte(data), 0600); e != nil {
			t.Fatal(e)
		}
		v := newEditor().Settings()
		if v.UI == nil || v.Recent == nil || v.SelectedViewer != 0 {
			t.Fatal("unsafe settings shape", v)
		}
	}
	stale := s.Settings()
	s.recent("latest.bms")
	stale.UI["zoom"] = 1.5
	if e := s.SaveSettings(stale); e != nil {
		t.Fatal(e)
	}
	if s.Settings().Recent[0] != "latest.bms" {
		t.Fatal("stale preference update lost recent file")
	}
	if e := s.ClearRecent(); e != nil {
		t.Fatal(e)
	}
	if len(s.Settings().Recent) != 0 {
		t.Fatal("history not cleared")
	}
}
func TestAuditMalformedRecoveryIsRetained(t *testing.T) {
	s := service(t)
	path := filepath.Join(s.configDir, "recovery.json")
	if e := os.WriteFile(path, []byte(`{"headers":{},"notes":null}`), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e := s.Recovery(); e == nil {
		t.Fatal("invalid recovery accepted")
	}
	if _, e := os.Stat(path); e != nil {
		t.Fatal("invalid recovery deleted")
	}
	copies, e := filepath.Glob(filepath.Join(s.configDir, "recovery-invalid-*.json"))
	if e != nil || len(copies) != 1 {
		t.Fatal("missing quarantine copy", e)
	}
	if e = s.BackupVersioned(chart.New(), 100); e != nil {
		t.Fatal(e)
	}
	data, e := os.ReadFile(copies[0])
	if e != nil || string(data) != `{"headers":{},"notes":null}` {
		t.Fatal("new edits destroyed invalid recovery data", e)
	}
}
func TestAuditCannotOverwriteIBMSCWithText(t *testing.T) {
	s := service(t)
	path := filepath.Join(t.TempDir(), "project.ibmsc")
	os.WriteFile(path, []byte("original binary"), 0600)
	s.dialogs = &fakeDialogs{save: path}
	if _, e := s.SaveDocument(chart.New(), true); e == nil {
		t.Fatal("binary target accepted")
	}
	b, _ := os.ReadFile(path)
	if string(b) != "original binary" {
		t.Fatal("project overwritten")
	}
}
func TestPlayerHelper(t *testing.T) {
	if os.Getenv("BMSE_TEST_PLAYER") != "1" {
		return
	}
	args := os.Args
	for i, a := range args {
		if a == "--" {
			b, _ := json.Marshal(args[i+1:])
			_ = os.WriteFile(os.Getenv("BMSE_TEST_PLAYER_RESULT"), b, 0600)
			os.Exit(0)
		}
	}
	os.Exit(3)
}
func TestExternalPlayerArguments(t *testing.T) {
	s := service(t)
	dir := t.TempDir()
	d := chart.New()
	d.Path = filepath.Join(dir, "chart with spaces.bms")
	if e := storage.Save(d, d.Path); e != nil {
		t.Fatal(e)
	}
	output := filepath.Join(dir, "args.json")
	t.Setenv("BMSE_TEST_PLAYER", "1")
	t.Setenv("BMSE_TEST_PLAYER_RESULT", output)
	exe, e := os.Executable()
	if e != nil {
		t.Fatal(e)
	}
	settings := s.Settings()
	settings.Viewer = exe
	settings.PlayArgs = []string{"-test.run=TestPlayerHelper", "--", "<filename>", "<measure>", "literal ; & text"}
	settings.StopArgs = []string{"-test.run=TestPlayerHelper", "--", "stop", "<measure>"}
	if e = s.SaveSettings(settings); e != nil {
		t.Fatal(e)
	}
	if e = s.Play(d, 12, false); e != nil {
		t.Fatal(e)
	}
	var args []string
	for i := 0; i < 60; i++ {
		if b, e := os.ReadFile(output); e == nil {
			_ = json.Unmarshal(b, &args)
			break
		}
		time.Sleep(25 * time.Millisecond)
	}
	if len(args) != 3 || args[1] != "12" || args[2] != "literal ; & text" {
		t.Fatalf("arguments altered: %#v", args)
	}
	if filepath.Dir(args[0]) != dir {
		t.Fatal("preview not in material directory")
	}
	if _, e = storage.Read(args[0], "Auto"); e != nil {
		t.Fatal(e)
	}
	_ = os.Remove(output)
	if e = s.Stop(); e != nil {
		t.Fatal(e)
	}
	args = nil
	for i := 0; i < 60; i++ {
		if b, e := os.ReadFile(output); e == nil {
			_ = json.Unmarshal(b, &args)
			break
		}
		time.Sleep(25 * time.Millisecond)
	}
	if len(args) != 2 || args[0] != "stop" || args[1] != "12" {
		t.Fatalf("invalid stop args %#v", args)
	}
}
