package main

import (
	"bmse/internal/chart"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// ReadLegacy reads only the known BMSE configuration files beside the selected bmse.ini.
func (s *EditorService) ReadLegacy(path string) (map[string]string, error) {
	result := map[string]string{}
	if path == "" {
		p, e := s.app.Dialog.OpenFile().SetTitle("选择旧版 bmse.ini").AddFilter("BMSE 配置", "bmse.ini;*.ini").PromptForSingleSelection()
		if e != nil {
			return nil, e
		}
		if p == "" {
			return result, nil
		}
		path = p
	}
	root := filepath.Dir(path)
	if absolute, e := filepath.Abs(root); e == nil {
		root = absolute
	}
	result["baseDirectory"] = root
	files := map[string]string{"bmse.ini": path, "shortcut.ini": filepath.Join(root, "shortcut.ini"), "bmse_viewer.ini": filepath.Join(root, "bmse_viewer.ini")}
	for _, dir := range []string{"lang", "theme"} {
		entries, e := os.ReadDir(filepath.Join(root, dir))
		if e != nil && !os.IsNotExist(e) {
			return nil, e
		}
		for _, entry := range entries {
			if !entry.IsDir() && filepath.Ext(entry.Name()) == ".ini" {
				files[dir+"/"+entry.Name()] = filepath.Join(root, dir, entry.Name())
			}
		}
	}
	total := 0
	for name, file := range files {
		f, e := os.Open(file)
		if os.IsNotExist(e) {
			continue
		}
		if e != nil {
			return nil, e
		}
		b, e := io.ReadAll(io.LimitReader(f, (1<<20)+1))
		f.Close()
		if e != nil {
			return nil, e
		}
		total += len(b)
		if len(b) > 1<<20 || total > 8<<20 {
			return nil, fmt.Errorf("legacy configuration is too large")
		}
		text, _, e := chart.Decode(b, "Auto")
		if e != nil {
			return nil, e
		}
		result[name] = text
	}
	return result, nil
}
