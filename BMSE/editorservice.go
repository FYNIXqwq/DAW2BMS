package main

import (
	"bmse/internal/chart"
	"bmse/internal/storage"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"mime"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/wailsapp/wails/v3/pkg/application"
)

type Viewer struct {
	Name     string   `json:"name"`
	Path     string   `json:"path"`
	PlayArgs []string `json:"playArgs"`
	AllArgs  []string `json:"allArgs"`
	StopArgs []string `json:"stopArgs"`
}
type Settings struct {
	Recent         []string       `json:"recent"`
	Viewer         string         `json:"viewer"`
	PlayArgs       []string       `json:"playArgs"`
	AllArgs        []string       `json:"allArgs"`
	StopArgs       []string       `json:"stopArgs"`
	UI             map[string]any `json:"ui"`
	Viewers        []Viewer       `json:"viewers"`
	SelectedViewer int            `json:"selectedViewer"`
}
type EditorService struct {
	app              *application.App
	window           *application.WebviewWindow
	dirty            atomic.Bool
	diskOperations   atomic.Int32
	recoveryRevision int64
	mu               sync.Mutex
	settings         Settings
	configDir        string
	player           *exec.Cmd
	previewPaths     []string
	dialogs          fileDialogs
	lastMeasure      int
	dawMu            sync.Mutex
	dawJob           *DawJob
	dawInspectBusy   bool
	dawCommand       func(context.Context, DawConfig) *exec.Cmd
}

func newEditor() *EditorService {
	dir, e := os.UserConfigDir()
	if e != nil {
		dir = os.TempDir()
	}
	dir = filepath.Join(dir, "BMSE-Wails")
	if override := os.Getenv("BMSE_CONFIG_DIR"); override != "" {
		dir = override
	}
	_ = os.MkdirAll(dir, 0700)
	s := &EditorService{configDir: dir, settings: Settings{Recent: []string{}, PlayArgs: []string{"-P", "-N<measure>", "<filename>"}, AllArgs: []string{"-P", "-N0", "<filename>"}, StopArgs: []string{"-S"}, UI: map[string]any{}}}
	if b, e := readLimitedJSON(filepath.Join(dir, "settings.json"), 8<<20); e == nil {
		v := s.settings
		if e = json.Unmarshal(b, &v); e == nil {
			s.settings = normalizeSettings(v)
		} else {
			s.settings.UI["configurationWarning"] = "设置文件无效，已使用默认设置；原文件未删除。"
		}
	} else if !os.IsNotExist(e) {
		s.settings.UI["configurationWarning"] = e.Error()
	}
	return s
}
func (s *EditorService) Settings() Settings { s.mu.Lock(); defer s.mu.Unlock(); return s.settings }
func (s *EditorService) SaveSettings(v Settings) error {
	if len(v.Viewers) > 0 {
		if v.SelectedViewer < 0 || v.SelectedViewer >= len(v.Viewers) {
			return fmt.Errorf("invalid selected player")
		}
		p := v.Viewers[v.SelectedViewer]
		v.Viewer = p.Path
		v.PlayArgs = p.PlayArgs
		v.AllArgs = p.AllArgs
		v.StopArgs = p.StopArgs
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	v.Recent = append([]string{}, s.settings.Recent...)
	return s.writeSettings(v)
}
func (s *EditorService) recent(path string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	settings := s.settings
	r := []string{path}
	for _, v := range settings.Recent {
		if v != path && len(r) < 10 {
			r = append(r, v)
		}
	}
	settings.Recent = r
	_ = s.writeSettings(settings)
}
func (s *EditorService) NewDocument() chart.Document { return chart.New() }
func (s *EditorService) StartupPath() string {
	for _, arg := range os.Args[1:] {
		ext := strings.ToLower(filepath.Ext(arg))
		if ext == ".bms" || ext == ".bme" || ext == ".bml" || ext == ".pms" || ext == ".ibmsc" {
			if p, e := filepath.Abs(arg); e == nil {
				return p
			}
		}
	}
	return ""
}
func (s *EditorService) OpenDirectory(path string) error {
	if path == "" {
		return fmt.Errorf("请先保存谱面")
	}
	dir, e := filepath.Abs(filepath.Dir(path))
	if e != nil {
		return e
	}
	if _, e = os.Stat(dir); e != nil {
		return e
	}
	cmd := exec.Command("explorer.exe", dir)
	if e = cmd.Start(); e != nil {
		return e
	}
	go func() { _ = cmd.Wait() }()
	return nil
}
func (s *EditorService) Open(path, encoding string) (*chart.Document, error) {
	if path == "" {
		p, e := s.fileDialogs().OpenChart()
		if e != nil {
			return nil, e
		}
		if p == "" {
			return nil, nil
		}
		path = p
	}
	d, e := storage.ReadWithLayout(path, encoding, s.Settings().UI["ibmscColumns"] == "extended")
	if e != nil {
		return nil, e
	}
	s.recent(path)
	return &d, nil
}
func (s *EditorService) Parse(text string) (chart.Document, error) {
	if len(text) > 32<<20 {
		return chart.New(), fmt.Errorf("chart exceeds 32 MiB")
	}
	return chart.Parse(text)
}
func (s *EditorService) Serialize(d chart.Document) (string, error) { return chart.Serialize(d) }
func (s *EditorService) DecodeDocument(data, encoding string) (chart.Document, error) {
	return chart.DecodeDocument(data, encoding)
}
func (s *EditorService) EncodeDocument(d chart.Document) (string, error) {
	return chart.EncodeDocument(d)
}
func (s *EditorService) ImportIBMSC(data string, extended bool) (chart.Document, error) {
	if len(data) > 45<<20 {
		return chart.New(), fmt.Errorf("project too large")
	}
	b, e := base64.StdEncoding.DecodeString(data)
	if e != nil {
		return chart.New(), e
	}
	return chart.ParseIBMSC(b, extended)
}
func (s *EditorService) Validate(d chart.Document) []chart.Issue { return chart.Validate(d) }
func (s *EditorService) Save(d chart.Document, saveAs bool) (string, error) {
	saved, e := s.SaveDocument(d, saveAs)
	if e != nil {
		return "", e
	}
	if saved == nil {
		return "", nil
	}
	return saved.Path, nil
}
func (s *EditorService) SaveDocument(d chart.Document, saveAs bool) (*chart.Document, error) {
	s.diskOperations.Add(1)
	defer s.diskOperations.Add(-1)
	path := d.Path
	if strings.EqualFold(filepath.Ext(path), ".ibmsc") {
		saveAs = true
		path = strings.TrimSuffix(path, filepath.Ext(path)) + ".bms"
	}
	if saveAs || path == "" {
		name := filepath.Base(path)
		if name == "." || name == "" {
			name = "untitled.bms"
			if d.EditorMode == "PMS" {
				name = "untitled.pms"
			}
		}
		p, e := s.fileDialogs().SaveChart(name)
		if e != nil {
			return nil, e
		}
		if p == "" {
			return nil, nil
		}
		path = p
		if filepath.Ext(path) == "" {
			path += ".bms"
		}
	}
	result, e := storage.Rebase(d, path)
	if strings.EqualFold(filepath.Ext(path), ".ibmsc") {
		return nil, fmt.Errorf("不能把 BMS 文本覆盖为 iBMSC 工程，请使用 .bms/.bme/.bml/.pms")
	}
	if e != nil {
		return nil, e
	}
	if e := storage.Save(result, path); e != nil {
		return nil, e
	}
	s.recent(path)
	return &result, nil
}
func (s *EditorService) SetDirty(value bool, title string) {
	s.dirty.Store(value)
	if s.window != nil {
		s.window.SetTitle(title)
	}
}
func (s *EditorService) Backup(d chart.Document) error {
	b, e := json.Marshal(d)
	if e != nil {
		return e
	}
	if len(b) > 128<<20 {
		return fmt.Errorf("恢复备份过大，请保存当前谱面")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return storage.AtomicWrite(filepath.Join(s.configDir, "recovery.json"), b)
}
func (s *EditorService) BackupVersioned(d chart.Document, revision int64) error {
	b, e := json.Marshal(d)
	if e != nil {
		return e
	}
	if len(b) > 128<<20 {
		return fmt.Errorf("恢复备份过大，请保存当前谱面")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if revision <= s.recoveryRevision {
		return nil
	}
	if e = storage.AtomicWrite(filepath.Join(s.configDir, "recovery.json"), b); e != nil {
		return e
	}
	s.recoveryRevision = revision
	return nil
}
func (s *EditorService) ClearRecoveryVersioned(revision int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if revision <= s.recoveryRevision {
		return nil
	}
	e := os.Remove(filepath.Join(s.configDir, "recovery.json"))
	if e != nil && !os.IsNotExist(e) {
		return e
	}
	s.recoveryRevision = revision
	return nil
}
func (s *EditorService) Recovery() (*chart.Document, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, e := readLimitedJSON(filepath.Join(s.configDir, "recovery.json"), 128<<20)
	if os.IsNotExist(e) {
		return nil, nil
	}
	if e != nil {
		return nil, e
	}
	var d chart.Document
	e = json.Unmarshal(b, &d)
	if e != nil || d.Headers == nil || d.WAV == nil || d.BMP == nil || d.BGA == nil || d.Measures == nil || d.Notes == nil || len(d.Notes) > 200000 {
		if archive, err := os.CreateTemp(s.configDir, "recovery-invalid-*.json"); err == nil {
			path := archive.Name()
			_, writeErr := archive.Write(b)
			if writeErr == nil {
				writeErr = archive.Sync()
			}
			closeErr := archive.Close()
			if writeErr == nil && closeErr == nil {
				return nil, fmt.Errorf("恢复文件结构不完整，已保留独立副本：%s", path)
			}
			_ = os.Remove(path)
		}
		return nil, fmt.Errorf("恢复文件结构不完整，原文件已保留：%s", filepath.Join(s.configDir, "recovery.json"))
	}
	return &d, e
}
func (s *EditorService) ClearRecovery() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	e := os.Remove(filepath.Join(s.configDir, "recovery.json"))
	if os.IsNotExist(e) {
		return nil
	}
	return e
}
func (s *EditorService) Quit() {
	if s.diskOperations.Load() > 0 {
		if s.app != nil {
			s.app.Event.Emit("operation-pending")
		}
		return
	}
	s.dirty.Store(false)
	for _, p := range s.previewPaths {
		_ = os.Remove(p)
	}
	s.app.Quit()
}
func (s *EditorService) PickViewer() (string, error) {
	return s.fileDialogs().PickViewer()
}
func (s *EditorService) PickMaterials(chartPath string, kind string) ([]string, error) {
	paths, e := s.fileDialogs().PickMaterials(kind)
	if e != nil {
		return nil, e
	}
	result := []string{}
	for _, p := range paths {
		if chartPath != "" {
			if r, e := filepath.Rel(filepath.Dir(chartPath), p); e == nil {
				p = r
			}
		}
		result = append(result, p)
	}
	return result, nil
}
func (s *EditorService) MaterialData(chartPath, name string) (string, error) {
	if name == "" {
		return "", fmt.Errorf("未设置素材")
	}
	path := name
	if !filepath.IsAbs(path) {
		if chartPath == "" {
			return "", fmt.Errorf("请先保存谱面，或选择绝对路径素材")
		}
		path = filepath.Join(filepath.Dir(chartPath), path)
	}
	// Players commonly substitute missing WAV extensions with OGG.
	if _, e := os.Stat(path); os.IsNotExist(e) {
		stem := strings.TrimSuffix(path, filepath.Ext(path))
		for _, ext := range []string{".ogg", ".wav", ".mp3", ".flac"} {
			if _, e := os.Stat(stem + ext); e == nil {
				path = stem + ext
				break
			}
		}
	}
	info, e := os.Stat(path)
	if e != nil {
		return "", e
	}
	if info.Size() > 64<<20 {
		return "", fmt.Errorf("预览素材超过 64 MiB")
	}
	b, e := os.ReadFile(path)
	if e != nil {
		return "", e
	}
	mt := mime.TypeByExtension(strings.ToLower(filepath.Ext(path)))
	if mt == "" {
		mt = "application/octet-stream"
	}
	return "data:" + mt + ";base64," + base64.StdEncoding.EncodeToString(b), nil
}

func (s *EditorService) MaterialPaths(chartPath string, paths []string) ([]string, error) {
	if len(paths) > 3844 {
		return nil, fmt.Errorf("素材数量过多")
	}
	result := make([]string, len(paths))
	for i, p := range paths {
		if chartPath != "" {
			if rel, e := filepath.Rel(filepath.Dir(chartPath), p); e == nil {
				p = rel
			}
		}
		result[i] = p
	}
	return result, nil
}
func (s *EditorService) Play(d chart.Document, measure int, all bool) error {
	if measure < 0 || measure > 999 {
		return fmt.Errorf("invalid start measure")
	}
	settings := s.Settings()
	if settings.Viewer == "" {
		return fmt.Errorf("请先在播放器设置中选择播放器")
	}
	if d.Path == "" {
		return fmt.Errorf("请先保存谱面，以确定素材目录")
	}
	ext := strings.ToLower(filepath.Ext(d.Path))
	if ext == ".ibmsc" || ext == "" {
		ext = ".bms"
	}
	f, e := os.CreateTemp(filepath.Dir(d.Path), "___bmse_preview_*"+ext)
	if e != nil {
		return e
	}
	path := f.Name()
	f.Close()
	if e = storage.Save(d, path); e != nil {
		os.Remove(path)
		return e
	}
	s.mu.Lock()
	s.previewPaths = append(s.previewPaths, path)
	s.lastMeasure = measure
	s.mu.Unlock()
	args := settings.PlayArgs
	if all {
		args = settings.AllArgs
	}
	expanded := make([]string, len(args))
	for i, a := range args {
		expanded[i] = strings.ReplaceAll(strings.ReplaceAll(a, "<filename>", path), "<measure>", fmt.Sprint(measure))
	}
	cmd := exec.Command(viewerPath(settings.Viewer), expanded...)
	cmd.Dir = filepath.Dir(d.Path)
	if e = cmd.Start(); e != nil {
		_ = os.Remove(path)
		return e
	}
	s.mu.Lock()
	s.player = cmd
	s.mu.Unlock()
	go func() { _ = cmd.Wait() }()
	return nil
}
func (s *EditorService) Stop() error {
	settings := s.Settings()
	if settings.Viewer != "" && len(settings.StopArgs) > 0 {
		s.mu.Lock()
		path := ""
		if len(s.previewPaths) > 0 {
			path = s.previewPaths[len(s.previewPaths)-1]
		}
		measure := s.lastMeasure
		s.mu.Unlock()
		args := make([]string, len(settings.StopArgs))
		for i, arg := range settings.StopArgs {
			args[i] = strings.ReplaceAll(strings.ReplaceAll(arg, "<filename>", path), "<measure>", fmt.Sprint(measure))
		}
		cmd := exec.Command(viewerPath(settings.Viewer), args...)
		if path != "" {
			cmd.Dir = filepath.Dir(path)
		}
		if e := cmd.Start(); e != nil {
			return e
		}
		go func() { _ = cmd.Wait() }()
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.player != nil && s.player.Process != nil {
		return s.player.Process.Kill()
	}
	return nil
}

func viewerPath(path string) string {
	if filepath.IsAbs(path) {
		return path
	}
	if exe, e := os.Executable(); e == nil {
		return filepath.Join(filepath.Dir(exe), path)
	}
	return path
}
