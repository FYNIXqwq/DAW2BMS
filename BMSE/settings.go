package main

import (
	"bmse/internal/storage"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

func normalizeSettings(s Settings) Settings {
	if s.UI == nil {
		s.UI = map[string]any{}
	}
	if s.Recent == nil {
		s.Recent = []string{}
	}
	if s.PlayArgs == nil {
		s.PlayArgs = []string{"<filename>"}
	}
	if s.AllArgs == nil {
		s.AllArgs = []string{"<filename>"}
	}
	if s.StopArgs == nil {
		s.StopArgs = []string{}
	}
	for i := range s.Viewers {
		p := &s.Viewers[i]
		if p.PlayArgs == nil {
			p.PlayArgs = []string{"<filename>"}
		}
		if p.AllArgs == nil {
			p.AllArgs = []string{"<filename>"}
		}
		if p.StopArgs == nil {
			p.StopArgs = []string{}
		}
	}
	if s.SelectedViewer < 0 || s.SelectedViewer >= len(s.Viewers) {
		s.SelectedViewer = 0
	}
	if len(s.Viewers) > 0 {
		p := s.Viewers[s.SelectedViewer]
		s.Viewer = p.Path
		s.PlayArgs = p.PlayArgs
		s.AllArgs = p.AllArgs
		s.StopArgs = p.StopArgs
	}
	return s
}
func readLimitedJSON(path string, limit int64) ([]byte, error) {
	f, e := os.Open(path)
	if e != nil {
		return nil, e
	}
	defer f.Close()
	b, e := io.ReadAll(io.LimitReader(f, limit+1))
	if int64(len(b)) > limit {
		return nil, fmt.Errorf("配置/恢复文件超过大小限制：%s", path)
	}
	return b, e
}

// Caller holds s.mu. Preferences and recent-history writes use one atomic critical section.
func (s *EditorService) writeSettings(v Settings) error {
	v = normalizeSettings(v)
	b, e := json.MarshalIndent(v, "", "  ")
	if e != nil {
		return e
	}
	if e = storage.AtomicWrite(filepath.Join(s.configDir, "settings.json"), b); e == nil {
		s.settings = v
	}
	return e
}
func (s *EditorService) ClearRecent() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	v := s.settings
	v.Recent = []string{}
	return s.writeSettings(v)
}
