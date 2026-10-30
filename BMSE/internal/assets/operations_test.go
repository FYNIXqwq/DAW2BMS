package assets

import (
	"bmse/internal/chart"
	"bmse/internal/storage"
	"os"
	"path/filepath"
	"testing"
)

func fixture(t *testing.T) (chart.Document, string) {
	t.Helper()
	dir := t.TempDir()
	d := chart.New()
	d.Path = filepath.Join(dir, "main.bms")
	d.WAV["1"] = "kick.wav"
	d.Notes = []chart.Note{{ID: "n", Channel: 37, Value: 1, Kind: "normal"}}
	for _, file := range []string{"kick.wav", "unused.wav", "shared.ogg", "preview.wav"} {
		if e := os.WriteFile(filepath.Join(dir, file), []byte("audio-"+file), 0600); e != nil {
			t.Fatal(e)
		}
	}
	d.Headers["PREVIEW"] = "preview.wav"
	if e := storage.Save(d, d.Path); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(filepath.Join(dir, "other.bms"), []byte("#BPM 130\n#WAV01 shared.wav\n"), 0600); e != nil {
		t.Fatal(e)
	}
	return d, dir
}
func TestCleanupProtectsReferencesAndRestores(t *testing.T) {
	d, dir := fixture(t)
	p, e := Prepare(d, "cleanup")
	if e != nil {
		t.Fatal(e)
	}
	if len(p.Changes) != 1 || p.Changes[0].From != "unused.wav" {
		t.Fatalf("incorrect cleanup plan %+v", p.Changes)
	}
	r, e := Execute(p)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = os.Stat(filepath.Join(dir, "unused.wav")); !os.IsNotExist(e) {
		t.Fatal("unused asset not moved")
	}
	if _, e = Restore(r.Journal); e != nil {
		t.Fatal(e)
	}
	if b, e := os.ReadFile(filepath.Join(dir, "unused.wav")); e != nil || string(b) != "audio-unused.wav" {
		t.Fatal("asset was not restored")
	}
}
func TestRenameUpdatesChartAndRestores(t *testing.T) {
	d, dir := fixture(t)
	d.WAV["2"] = "kick.wav"
	if e := storage.Save(d, d.Path); e != nil {
		t.Fatal(e)
	}
	p, e := Prepare(d, "rename")
	if e != nil {
		t.Fatal(e)
	}
	r, e := Execute(p)
	if e != nil {
		t.Fatal(e)
	}
	saved, e := storage.Read(d.Path, "Auto")
	if e != nil || saved.WAV["1"] != "01.wav" || saved.WAV["2"] != "01.wav" {
		t.Fatal("references not updated", e)
	}
	if _, e = os.Stat(filepath.Join(dir, "01.wav")); e != nil {
		t.Fatal(e)
	}
	original, e := Restore(r.Journal)
	if e != nil || original.WAV["1"] != "kick.wav" {
		t.Fatal("chart not restored", e)
	}
}
func TestPlanRejectsStaleAndConflictingChanges(t *testing.T) {
	d, dir := fixture(t)
	p, e := Prepare(d, "cleanup")
	if e != nil {
		t.Fatal(e)
	}
	_ = os.WriteFile(filepath.Join(dir, "unused.wav"), []byte("changed"), 0600)
	if _, e = Execute(p); e == nil {
		t.Fatal("stale media accepted")
	}
	p, e = Prepare(d, "cleanup")
	if e != nil {
		t.Fatal(e)
	}
	_ = os.WriteFile(filepath.Join(dir, "new.bms"), []byte("#WAV01 unused.wav"), 0600)
	if _, e = Execute(p); e == nil {
		t.Fatal("new sibling chart was ignored")
	}
}
func TestReferenceNormalizationAndUnsavedGuard(t *testing.T) {
	d, dir := fixture(t)
	d.WAV["1"] = ".\\kick.wav"
	d.WAV["2"] = filepath.Join(dir, "unused.wav")
	if e := storage.Save(d, d.Path); e != nil {
		t.Fatal(e)
	}
	p, e := Prepare(d, "cleanup")
	if e != nil || len(p.Changes) != 0 {
		t.Fatal("absolute or dot-relative asset lost", p.Changes, e)
	}
	d.Headers["TITLE"] = "unsaved"
	if _, e = Prepare(d, "cleanup"); e == nil {
		t.Fatal("unsaved chart accepted")
	}
}
func TestRestoreDoesNotOverwriteNewFiles(t *testing.T) {
	d, dir := fixture(t)
	p, e := Prepare(d, "rename")
	if e != nil {
		t.Fatal(e)
	}
	r, e := Execute(p)
	if e != nil {
		t.Fatal(e)
	}
	_ = os.WriteFile(filepath.Join(dir, "kick.wav"), []byte("new user content"), 0600)
	if _, e = Restore(r.Journal); e == nil {
		t.Fatal("new file overwritten")
	}
	b, _ := os.ReadFile(filepath.Join(dir, "kick.wav"))
	if string(b) != "new user content" {
		t.Fatal("new data damaged")
	}
}
func TestRejectTraversal(t *testing.T) {
	d, _ := fixture(t)
	for _, name := range []string{"../outside.wav", "sub/../../outside.wav"} {
		if _, e := safe(filepath.Dir(d.Path), name); e == nil {
			t.Fatal("traversal accepted")
		}
	}
}

func TestMoveNeverReplacesExistingFile(t *testing.T) {
	dir := t.TempDir()
	src, dst := filepath.Join(dir, "source"), filepath.Join(dir, "target")
	_ = os.WriteFile(src, []byte("source"), 0600)
	_ = os.WriteFile(dst, []byte("target"), 0600)
	if e := moveNoReplace(src, dst); e == nil {
		t.Fatal("existing destination replaced")
	}
	data, _ := os.ReadFile(dst)
	if string(data) != "target" {
		t.Fatal("target contents changed")
	}
}

func TestAuditRestoreRetainsExplicitEncoding(t *testing.T) {
	d, dir := fixture(t)
	d.Encoding = "EUC-KR"
	d.Headers["TITLE"] = "한국어"
	if e := storage.Save(d, d.Path); e != nil {
		t.Fatal(e)
	}
	plan, e := Prepare(d, "cleanup")
	if e != nil {
		t.Fatal(e)
	}
	result, e := Execute(plan)
	if e != nil {
		t.Fatal(e)
	}
	restored, e := Restore(result.Journal)
	if e != nil || restored.Encoding != "EUC-KR" || restored.Headers["TITLE"] != "한국어" {
		t.Fatal(restored.Encoding, e)
	}
	if _, e = os.Stat(filepath.Join(dir, "unused.wav")); e != nil {
		t.Fatal(e)
	}
}

func TestAuditRenameOneUpdatesAllReferencesAndRestores(t *testing.T) {
	d, dir := fixture(t)
	d.WAV["2"] = "kick.wav"
	d.Headers["PREVIEW"] = "kick.wav"
	if e := storage.Save(d, d.Path); e != nil {
		t.Fatal(e)
	}
	p, e := PrepareRename(d, "kick.wav", "kick new.wav")
	if e != nil {
		t.Fatal(e)
	}
	r, e := Execute(p)
	if e != nil {
		t.Fatal(e)
	}
	if r.Document.WAV["1"] != "kick new.wav" || r.Document.WAV["2"] != "kick new.wav" || r.Document.Headers["PREVIEW"] != "kick new.wav" {
		t.Fatal("stale references")
	}
	if _, e = Restore(r.Journal, filepath.Join(dir, "other.bms")); e == nil {
		t.Fatal("restored wrong chart")
	}
	if _, e = Restore(r.Journal, d.Path); e != nil {
		t.Fatal(e)
	}
}
