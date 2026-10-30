package storage

import (
	"bmse/internal/chart"
	"os"
	"path/filepath"
	"testing"
)

func TestFailedSaveLeavesOriginal(t *testing.T) {
	p := filepath.Join(t.TempDir(), "chart.bms")
	original := []byte("#TITLE original\n")
	if e := os.WriteFile(p, original, 0600); e != nil {
		t.Fatal(e)
	}
	d := chart.New()
	d.Notes = append(d.Notes, chart.Note{ID: "bad", Channel: 37, Measure: 1001, Value: 1})
	if e := Save(d, p); e == nil {
		t.Fatal("invalid chart saved")
	}
	b, e := os.ReadFile(p)
	if e != nil || string(b) != string(original) {
		t.Fatal("original file changed on failed save")
	}
}
func TestAtomicReplacement(t *testing.T) {
	p := filepath.Join(t.TempDir(), "chart.bms")
	for _, title := range []string{"first", "second"} {
		d := chart.New()
		d.Headers["TITLE"] = title
		if e := Save(d, p); e != nil {
			t.Fatal(e)
		}
		r, e := Read(p, "Auto")
		if e != nil || r.Headers["TITLE"] != title {
			t.Fatal("replacement failed", e)
		}
	}
	files, _ := filepath.Glob(filepath.Join(filepath.Dir(p), ".bmse-*"))
	if len(files) > 0 {
		t.Fatal("temporary files leaked")
	}
}
