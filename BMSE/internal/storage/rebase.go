package storage

import (
	"bmse/internal/chart"
	"encoding/json"
	"path/filepath"
	"regexp"
	"strings"
)

var assetDefinition = regexp.MustCompile(`(?i)^(\s*#(?:WAV[0-9a-z]{2}|BMP[0-9a-z]{2}|STAGEFILE|BANNER|BACKBMP|PREVIEW)\s+)(.*)$`)

func Rebase(d chart.Document, destination string) (chart.Document, error) {
	bytes, e := json.Marshal(d)
	if e != nil {
		return d, e
	}
	var next chart.Document
	if e = json.Unmarshal(bytes, &next); e != nil {
		return d, e
	}
	if d.Path == "" {
		next.Path = destination
		return next, nil
	}
	oldDir, e := filepath.Abs(filepath.Dir(d.Path))
	if e != nil {
		return d, e
	}
	newDir, e := filepath.Abs(filepath.Dir(destination))
	if e != nil {
		return d, e
	}
	if strings.EqualFold(oldDir, newDir) {
		next.Path = destination
		return next, nil
	}
	rebase := func(name string) string {
		if name == "" || filepath.IsAbs(name) {
			return name
		}
		absolute := filepath.Join(oldDir, filepath.FromSlash(strings.ReplaceAll(name, "\\", "/")))
		relative, e := filepath.Rel(newDir, absolute)
		if e != nil {
			return absolute
		}
		return relative
	}
	raw := func(text string) string {
		lines := strings.Split(text, "\n")
		for i, line := range lines {
			suffix := ""
			if strings.HasSuffix(line, "\r") {
				suffix = "\r"
				line = strings.TrimSuffix(line, "\r")
			}
			if m := assetDefinition.FindStringSubmatch(line); m != nil {
				lines[i] = m[1] + rebase(m[2]) + suffix
			}
		}
		return strings.Join(lines, "\n")
	}
	if d.SourceText != "" {
		source, e := chart.Serialize(d)
		if e != nil {
			return d, e
		}
		next, e = chart.Parse(raw(source))
		if e != nil {
			return d, e
		}
		next.Encoding = d.Encoding
		next.EditorMode = d.EditorMode
	} else {
		for _, table := range []map[string]string{next.WAV, next.BMP} {
			for id, name := range table {
				table[id] = rebase(name)
			}
		}
		for _, key := range []string{"STAGEFILE", "BANNER", "BACKBMP", "PREVIEW"} {
			if v, ok := next.Headers[key]; ok {
				next.Headers[key] = rebase(v)
			}
		}
		next.Extra = strings.Split(raw(strings.Join(next.Extra, "\n")), "\n")
		if len(d.Extra) == 0 {
			next.Extra = []string{}
		}
	}
	next.Path = destination
	return next, nil
}
