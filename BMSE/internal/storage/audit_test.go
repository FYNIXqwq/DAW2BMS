package storage

import (
	"bmse/internal/chart"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAuditSaveAsRebasesEveryAsset(t *testing.T) {
	dir := t.TempDir()
	old, newdir := filepath.Join(dir, "old"), filepath.Join(dir, "new")
	os.Mkdir(old, 0700)
	os.Mkdir(newdir, 0700)
	d := chart.New()
	d.Path = filepath.Join(old, "old.bms")
	d.WAV["1"] = "sound.wav"
	d.BMP["1"] = "cover.png"
	for _, key := range []string{"PREVIEW", "BANNER", "BACKBMP", "STAGEFILE"} {
		d.Headers[key] = "cover.png"
	}
	r, e := Rebase(d, filepath.Join(newdir, "copy.bms"))
	if e != nil {
		t.Fatal(e)
	}
	if filepath.Clean(filepath.Join(newdir, r.WAV["1"])) != filepath.Join(old, "sound.wav") {
		t.Fatal(r.WAV)
	}
	for _, key := range []string{"PREVIEW", "BANNER", "BACKBMP", "STAGEFILE"} {
		if filepath.Clean(filepath.Join(newdir, r.Headers[key])) != filepath.Join(old, "cover.png") {
			t.Fatal(key)
		}
	}
	if d.WAV["1"] != "sound.wav" {
		t.Fatal("source document mutated")
	}
}
func TestAuditSaveAsConditionalPathsAndOrder(t *testing.T) {
	root := t.TempDir()
	old, newdir := filepath.Join(root, "old"), filepath.Join(root, "new")
	os.Mkdir(old, 0700)
	os.Mkdir(newdir, 0700)
	d, e := chart.Parse("#BPM 130\n#RANDOM 2\n#IF 1\n#WAV01 one.wav\n#00011:01\n#ELSE\n#WAV01 two.wav\n#ENDIF\n#ENDRANDOM")
	if e != nil {
		t.Fatal(e)
	}
	d.Path = filepath.Join(old, "a.bms")
	r, e := Rebase(d, filepath.Join(newdir, "b.bms"))
	if e != nil {
		t.Fatal(e)
	}
	text, e := chart.Serialize(r)
	if e != nil || !strings.Contains(text, filepath.Join("..", "old", "one.wav")) || !strings.Contains(text, filepath.Join("..", "old", "two.wav")) {
		t.Fatal(text, e)
	}
}
