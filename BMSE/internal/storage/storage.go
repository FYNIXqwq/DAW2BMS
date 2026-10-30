package storage

import (
	"bmse/internal/chart"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func Read(path, encoding string) (chart.Document, error) {
	return ReadWithLayout(path, encoding, false)
}

func ReadWithLayout(path, encoding string, extended bool) (chart.Document, error) {
	d := chart.New()
	f, e := os.Open(path)
	if e != nil {
		return d, e
	}
	defer f.Close()
	data, e := io.ReadAll(io.LimitReader(f, (32<<20)+1))
	if e != nil {
		return d, e
	}
	if len(data) > 32<<20 {
		return d, fmt.Errorf("file exceeds 32 MiB")
	}
	if len(data) >= 5 && string(data[:5]) == "iBMSC" {
		d, e = chart.ParseIBMSC(data, extended)
		d.Path = path
		return d, e
	}
	text, enc, e := chart.Decode(data, encoding)
	if e != nil {
		return d, e
	}
	d, e = chart.Parse(text)
	d.Path = path
	d.Encoding = enc
	if e == nil && d.DawDraft == nil && !strings.Contains(text, "*BMSE_DAW1 ") {
		if err := loadDawMapping(&d, data); err != nil {
			d.Warnings = append(d.Warnings, "DAW_MAPPING_INVALID: "+err.Error())
		}
	}
	return d, e
}

func Save(d chart.Document, path string) error {
	text, e := chart.Serialize(d)
	if e != nil {
		return e
	}
	data, e := chart.Encode(text, d.Encoding)
	if e != nil {
		return fmt.Errorf("cannot encode %s: %w", d.Encoding, e)
	}
	if len(data) > 32<<20 {
		return fmt.Errorf("encoded file exceeds 32 MiB")
	}
	return AtomicWrite(path, data)
}

// A temporary file on the same volume is flushed before replacing the target.
func AtomicWrite(path string, data []byte) error {
	f, e := os.CreateTemp(filepath.Dir(path), ".bmse-*")
	if e != nil {
		return e
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if _, e = f.Write(data); e != nil {
		f.Close()
		return e
	}
	if e = f.Sync(); e != nil {
		f.Close()
		return e
	}
	if e = f.Close(); e != nil {
		return e
	}
	return replace(tmp, path)
}
