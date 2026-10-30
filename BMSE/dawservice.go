package main

import (
	"bmse/internal/chart"
	"bmse/internal/storage"
	"bufio"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

// The Python engine is configurable and invoked without a shell. DAW inputs
// are JSON on stdin, never command text. Generated media stays beside its BMS.
type DawConfig struct {
	Mode             string `json:"mode,omitempty"`
	BundledAvailable bool   `json:"bundledAvailable"`
	Python           string `json:"python"`
	EngineRoot       string `json:"engineRoot"`
	Language         string `json:"language"`
	SystemLanguage   string `json:"systemLanguage,omitempty"`
}
type DawTrack struct {
	ID        int    `json:"id"`
	Name      string `json:"name"`
	Notes     int    `json:"notes"`
	Supported bool   `json:"supported"`
}
type DawArrangement struct {
	ID     int        `json:"id"`
	Name   string     `json:"name"`
	Tracks []DawTrack `json:"tracks"`
}
type DawPreview struct {
	Path         string           `json:"path"`
	SHA256       string           `json:"sha256"`
	DAW          string           `json:"daw"`
	Arrangements []DawArrangement `json:"arrangements"`
}
type DawRequest struct {
	Source        string   `json:"source"`
	SourceHash    string   `json:"sourceHash"`
	OutputParent  string   `json:"outputParent"`
	Language      string   `json:"language"`
	Arrangement   int      `json:"arrangement"`
	PlayTracks    []int    `json:"playTracks"`
	ExcludeTracks []int    `json:"excludeTracks"`
	AbletonRender bool     `json:"abletonRender"`
	FLExe         string   `json:"flExe"`
	AbletonExe    string   `json:"abletonExe"`
	Title         string   `json:"title"`
	Artist        string   `json:"artist"`
	InitialTail   float64  `json:"initialTail"`
	MaxTail       float64  `json:"maxTail"`
	MaxAttempts   int      `json:"maxAttempts"`
	ThresholdDB   float64  `json:"thresholdDB"`
	Timeout       float64  `json:"timeout"`
	LeadInBars    int      `json:"leadInBars"`
	Deduplicate   bool     `json:"deduplicate"`
	ResourceDirs  []string `json:"resourceDirs"`
}
type DawLog struct {
	Message string `json:"message"`
	Level   string `json:"level"`
}
type DawResult struct {
	Status          string `json:"status"`
	OutputDirectory string `json:"output_directory"`
	Chart           string `json:"chart"`
	MIDI            string `json:"midi"`
	FallbackMIDI    string `json:"fallback_midi"`
	AudioComplete   bool   `json:"audio_complete"`
	PlayableNotes   int    `json:"playable_notes"`
	BGMEvents       int    `json:"bgm_events"`
	MIDIOnlyNotes   int    `json:"midi_only_notes"`
}
type DawJob struct {
	ID              string     `json:"id"`
	Status          string     `json:"status"`
	Source          string     `json:"source"`
	OutputDir       string     `json:"outputDir"`
	Stage           int        `json:"stage"`
	Logs            []DawLog   `json:"logs"`
	Result          *DawResult `json:"result"`
	Error           string     `json:"error"`
	CancelRequested bool       `json:"cancelRequested"`
	input           io.WriteCloser
}
type dawEvent struct {
	Type     string          `json:"type"`
	Protocol int             `json:"protocol"`
	Message  string          `json:"message"`
	Level    string          `json:"level"`
	Stage    int             `json:"stage"`
	Data     json.RawMessage `json:"data"`
}

type dawStderr struct {
	mu   sync.Mutex
	data []byte
}

func (b *dawStderr) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	n := len(p)
	remaining := 32768 - len(b.data)
	if remaining > 0 {
		if len(p) > remaining {
			p = p[:remaining]
		}
		b.data = append(b.data, p...)
	}
	return n, nil
}
func (b *dawStderr) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return strings.TrimSpace(string(b.data))
}

func (s *EditorService) DawSettings() (DawConfig, error) {
	s.dawMu.Lock()
	defer s.dawMu.Unlock()
	exe, _ := os.Executable()
	cwd, _ := os.Getwd()
	cfg := dawDefaultConfig(exe, cwd, os.Getenv("DAW2BMS_PYTHON"), os.Getenv("DAW2BMS_ROOT"))
	path := filepath.Join(s.configDir, "daw-import.json")
	if _, e := os.Stat(path); os.IsNotExist(e) {
		if exe, e := os.Executable(); e == nil {
			path = filepath.Join(filepath.Dir(exe), "daw-import.json")
		}
	}
	if b, e := readLimitedJSON(path, 64<<10); e == nil {
		var saved DawConfig
		if e = json.Unmarshal(b, &saved); e != nil {
			return cfg, fmt.Errorf("DAW_CONFIG: %w", e)
		}
		// Existing explicit Python settings remain usable after the upgrade.
		if saved.Mode == "" {
			saved.Mode = "python"
		}
		cfg = saved
	} else if !os.IsNotExist(e) {
		return cfg, fmt.Errorf("DAW_CONFIG: %w", e)
	}
	cfg.SystemLanguage = dawSystemLanguage()
	cfg.BundledAvailable = dawBundlePath() != ""
	return cfg, nil
}
func validateDawConfig(cfg DawConfig) error {
	if cfg.Mode == "bundled" {
		if dawBundlePath() == "" {
			return fmt.Errorf("DAW_BUNDLE: restore the daw-engine folder beside BMSE3.exe")
		}
		return nil
	}
	if cfg.Mode != "" && cfg.Mode != "python" {
		return fmt.Errorf("DAW_CONFIG: unknown engine mode")
	}
	if cfg.Python == "" {
		return fmt.Errorf("DAW_ENGINE: choose a Python executable")
	}
	if _, e := exec.LookPath(cfg.Python); e != nil {
		return fmt.Errorf("DAW_ENGINE: %w", e)
	}
	if cfg.EngineRoot != "" {
		if info, e := os.Stat(filepath.Join(cfg.EngineRoot, "daw2bms", "bridge.py")); e != nil || info.IsDir() {
			return fmt.Errorf("DAW_ENGINE: engine folder must contain daw2bms/bridge.py")
		}
	}
	return nil
}
func (s *EditorService) DawSaveSettings(cfg DawConfig) error {
	cfg.Python = strings.Trim(strings.TrimSpace(cfg.Python), "\"")
	cfg.EngineRoot = strings.Trim(strings.TrimSpace(cfg.EngineRoot), "\"")
	cfg.SystemLanguage = ""
	cfg.BundledAvailable = false
	if cfg.Mode == "bundled" {
		cfg.Python, cfg.EngineRoot = "", ""
	}
	if e := validateDawConfig(cfg); e != nil {
		return e
	}
	s.dawMu.Lock()
	defer s.dawMu.Unlock()
	if s.dawInspectBusy || (s.dawJob != nil && s.dawJob.Status == "running") {
		return fmt.Errorf("DAW_BUSY")
	}
	b, e := json.MarshalIndent(cfg, "", "  ")
	if e != nil {
		return e
	}
	return storage.AtomicWrite(filepath.Join(s.configDir, "daw-import.json"), b)
}
func (s *EditorService) DawPick(kind string) (string, error) {
	if s.app == nil {
		return "", fmt.Errorf("DAW_DESKTOP")
	}
	switch kind {
	case "source":
		return s.app.Dialog.OpenFile().SetTitle("DAW project / DAW 工程").AddFilter("FL Studio / Ableton Live", "*.flp;*.als").PromptForSingleSelection()
	case "python":
		return s.app.Dialog.OpenFile().SetTitle("Python executable").AddFilter("Python", "*.exe").PromptForSingleSelection()
	case "engine", "output", "resources":
		return s.app.Dialog.OpenFile().SetTitle("Select directory / 选择目录").CanChooseFiles(false).CanChooseDirectories(true).PromptForSingleSelection()
	case "fl", "ableton":
		return s.app.Dialog.OpenFile().SetTitle("DAW executable").AddFilter("Executable", "*.exe").PromptForSingleSelection()
	}
	return "", fmt.Errorf("DAW_INPUT: unknown picker")
}
func dawSource(path string) (string, error) {
	path = strings.Trim(strings.TrimSpace(path), "\"")
	p, e := filepath.Abs(path)
	if e != nil {
		return "", e
	}
	p, e = filepath.EvalSymlinks(p)
	if e != nil {
		return "", fmt.Errorf("DAW_INPUT: %w", e)
	}
	ext := strings.ToLower(filepath.Ext(p))
	if ext != ".flp" && ext != ".als" {
		return "", fmt.Errorf("DAW_INPUT: select FLP or ALS")
	}
	info, e := os.Stat(p)
	if e != nil || !info.Mode().IsRegular() {
		return "", fmt.Errorf("DAW_INPUT: source file unavailable")
	}
	return p, nil
}
func (s *EditorService) dawCommandFor(ctx context.Context, cfg DawConfig) *exec.Cmd {
	if s.dawCommand != nil {
		return s.dawCommand(ctx, cfg)
	}
	if cfg.Mode == "bundled" {
		cmd := exec.CommandContext(ctx, dawBundlePath(), "--bridge")
		cmd.Dir = filepath.Dir(dawBundlePath())
		hideDawProcess(cmd)
		return cmd
	}
	cmd := exec.CommandContext(ctx, cfg.Python, "-u", "-m", "daw2bms.bridge")
	cmd.Env = os.Environ()
	if cfg.EngineRoot != "" {
		cmd.Dir = cfg.EngineRoot
		cmd.Env = append(cmd.Env, "PYTHONPATH="+cfg.EngineRoot+string(os.PathListSeparator)+os.Getenv("PYTHONPATH"))
	} else if p, e := exec.LookPath(cfg.Python); e == nil {
		cmd.Dir = filepath.Dir(p)
	}
	hideDawProcess(cmd)
	return cmd
}
func consumeDaw(reader io.Reader, handle func(dawEvent) error) error {
	scanner := bufio.NewScanner(io.LimitReader(reader, 128<<20))
	scanner.Buffer(make([]byte, 64<<10), 16<<20)
	hello := false
	terminal := false
	for scanner.Scan() {
		var event dawEvent
		if e := json.Unmarshal(scanner.Bytes(), &event); e != nil {
			return fmt.Errorf("DAW_PROTOCOL: %w", e)
		}
		if !hello {
			if event.Type != "hello" || event.Protocol != 1 {
				if event.Type == "error" {
					return fmt.Errorf("%s", event.Message)
				}
				return fmt.Errorf("DAW_PROTOCOL: incompatible bridge")
			}
			hello = true
		} else if terminal {
			return fmt.Errorf("DAW_PROTOCOL: event after completion")
		}
		if event.Type == "error" {
			return fmt.Errorf("%s", event.Message)
		}
		if event.Type == "tracks" || event.Type == "result" || event.Type == "cancelled" {
			terminal = true
		}
		if e := handle(event); e != nil {
			return e
		}
	}
	if e := scanner.Err(); e != nil {
		return e
	}
	if !hello || !terminal {
		return fmt.Errorf("DAW_PROTOCOL: bridge ended without a result")
	}
	return nil
}
func (s *EditorService) DawInspect(source, language string) (*DawPreview, error) {
	cfg, e := s.DawSettings()
	if e != nil {
		return nil, e
	}
	if e = validateDawConfig(cfg); e != nil {
		return nil, e
	}
	source, e = dawSource(source)
	if e != nil {
		return nil, e
	}
	s.dawMu.Lock()
	if s.dawInspectBusy || (s.dawJob != nil && s.dawJob.Status == "running") {
		s.dawMu.Unlock()
		return nil, fmt.Errorf("DAW_BUSY")
	}
	s.dawInspectBusy = true
	s.diskOperations.Add(1)
	s.dawMu.Unlock()
	defer func() { s.dawMu.Lock(); s.dawInspectBusy = false; s.dawMu.Unlock(); s.diskOperations.Add(-1) }()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	cmd := s.dawCommandFor(ctx, cfg)
	request, _ := json.Marshal(map[string]any{"protocol": 1, "action": "inspect", "source": source, "language": language})
	cmd.Stdin = strings.NewReader(string(request) + "\n")
	out, e := cmd.StdoutPipe()
	if e != nil {
		return nil, e
	}
	// stderr may include third-party diagnostics, but cannot grow a memory buffer.
	stderr := &dawStderr{}
	cmd.Stderr = stderr
	if e = cmd.Start(); e != nil {
		return nil, fmt.Errorf("DAW_ENGINE: %w", e)
	}
	var preview *DawPreview
	e = consumeDaw(out, func(event dawEvent) error {
		if event.Type == "tracks" {
			var p DawPreview
			if e := json.Unmarshal(event.Data, &p); e != nil {
				return e
			}
			preview = &p
		}
		return nil
	})
	if e != nil {
		cancel()
	}
	exitErr := cmd.Wait()
	if e != nil && stderr.String() != "" {
		e = fmt.Errorf("DAW_ENGINE: %v\n%s", e, stderr.String())
	}
	if e != nil {
		return nil, e
	}
	if exitErr != nil {
		return nil, fmt.Errorf("DAW_ENGINE: %w", exitErr)
	}
	if preview == nil || !sameDawPath(preview.Path, source) || len(preview.SHA256) != 64 {
		return nil, fmt.Errorf("DAW_PROTOCOL: invalid track preview")
	}
	return preview, nil
}
func sameDawPath(a, b string) bool {
	a = filepath.Clean(a)
	b = filepath.Clean(b)
	if runtime.GOOS == "windows" {
		return strings.EqualFold(a, b)
	}
	return a == b
}
func (s *EditorService) DawStart(request DawRequest) (*DawJob, error) {
	cfg, e := s.DawSettings()
	if e != nil {
		return nil, e
	}
	if e = validateDawConfig(cfg); e != nil {
		return nil, e
	}
	request.Source, e = dawSource(request.Source)
	if e != nil {
		return nil, e
	}
	if b, e := hex.DecodeString(request.SourceHash); e != nil || len(b) != 32 {
		return nil, fmt.Errorf("DAW_INPUT: read tracks first")
	}
	if request.MaxAttempts < 1 || request.MaxAttempts > 20 || request.Timeout < 1 || request.Timeout > 7200 || request.InitialTail < .1 || request.MaxTail < request.InitialTail || request.MaxTail > 1200 || request.ThresholdDB < -120 || request.ThresholdDB > -20 || request.LeadInBars < 0 || request.LeadInBars > 998 {
		return nil, fmt.Errorf("DAW_INPUT: invalid rendering options")
	}
	parent := strings.Trim(strings.TrimSpace(request.OutputParent), "\"")
	if parent == "" {
		parent = filepath.Join(filepath.Dir(request.Source), "output")
	}
	parent, e = filepath.Abs(parent)
	if e != nil {
		return nil, e
	}
	s.dawMu.Lock()
	defer s.dawMu.Unlock()
	if s.dawInspectBusy || (s.dawJob != nil && s.dawJob.Status == "running") {
		return nil, fmt.Errorf("DAW_BUSY")
	}
	if e = os.MkdirAll(parent, 0700); e != nil {
		return nil, e
	}
	parent, e = filepath.EvalSymlinks(parent)
	if e != nil {
		return nil, e
	}
	var token [8]byte
	if _, e = rand.Read(token[:]); e != nil {
		return nil, e
	}
	id := hex.EncodeToString(token[:])
	stem := []rune(strings.TrimSuffix(filepath.Base(request.Source), filepath.Ext(request.Source)))
	if len(stem) > 64 {
		stem = stem[:64]
	}
	output := filepath.Join(parent, string(stem)+"-bms-"+id[:8])
	if _, e = os.Stat(output); !os.IsNotExist(e) {
		return nil, fmt.Errorf("DAW_INPUT: output already exists")
	}
	job := &DawJob{ID: id, Status: "running", Source: request.Source, OutputDir: output, Logs: []DawLog{}}
	s.dawJob = job
	s.diskOperations.Add(1)
	go s.runDaw(job, cfg, request)
	return cloneDawJob(job), nil
}
func cloneDawJob(job *DawJob) *DawJob {
	if job == nil {
		return nil
	}
	v := *job
	v.Logs = append([]DawLog{}, job.Logs...)
	v.input = nil
	if job.Result != nil {
		r := *job.Result
		v.Result = &r
	}
	return &v
}
func (s *EditorService) DawStatus() *DawJob {
	s.dawMu.Lock()
	defer s.dawMu.Unlock()
	return cloneDawJob(s.dawJob)
}
func (s *EditorService) appendDawLog(job *DawJob, message, level string) {
	chars := []rune(message)
	if len(chars) > 4096 {
		message = string(chars[:4096]) + "…"
	}
	job.Logs = append(job.Logs, DawLog{message, level})
	if len(job.Logs) > 512 {
		job.Logs = job.Logs[len(job.Logs)-512:]
	}
}
func (s *EditorService) runDaw(job *DawJob, cfg DawConfig, request DawRequest) {
	defer s.diskOperations.Add(-1)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	cmd := s.dawCommandFor(ctx, cfg)
	options := map[string]any{"source_sha256": request.SourceHash, "arrangement_id": request.Arrangement,
		"play_tracks": append([]int{}, request.PlayTracks...), "exclude_tracks": append([]int{}, request.ExcludeTracks...),
		"ableton_render": request.AbletonRender, "initial_tail": request.InitialTail, "max_tail": request.MaxTail,
		"max_attempts": request.MaxAttempts, "threshold_db": request.ThresholdDB, "timeout": request.Timeout,
		"lead_in_bars": request.LeadInBars, "deduplicate": request.Deduplicate, "resource_dirs": append([]string{}, request.ResourceDirs...), "encoding": "utf-8"}
	for key, v := range map[string]string{"fl_exe": request.FLExe, "ableton_exe": request.AbletonExe, "title": request.Title, "artist": request.Artist} {
		if v != "" {
			options[key] = v
		}
	}
	input, e := cmd.StdinPipe()
	if e != nil {
		s.finishDaw(job, e)
		return
	}
	out, e := cmd.StdoutPipe()
	if e != nil {
		_ = input.Close()
		s.finishDaw(job, e)
		return
	}
	stderr := &dawStderr{}
	cmd.Stderr = stderr
	if e = cmd.Start(); e != nil {
		_ = input.Close()
		s.finishDaw(job, fmt.Errorf("DAW_ENGINE: %w", e))
		return
	}
	defer input.Close()
	e = json.NewEncoder(input).Encode(map[string]any{"protocol": 1, "action": "convert", "source": request.Source, "out": job.OutputDir, "language": request.Language, "options": options})
	s.dawMu.Lock()
	job.input = input
	if job.CancelRequested {
		_, _ = io.WriteString(input, "{\"action\":\"cancel\"}\n")
	}
	s.dawMu.Unlock()
	if e == nil {
		e = consumeDaw(out, func(event dawEvent) error {
			s.dawMu.Lock()
			defer s.dawMu.Unlock()
			switch event.Type {
			case "progress":
				s.appendDawLog(job, event.Message, event.Level)
				if event.Stage > 0 {
					job.Stage = event.Stage
				}
			case "result", "cancelled":
				var result DawResult
				if e := json.Unmarshal(event.Data, &result); e != nil {
					return e
				}
				if !sameDawPath(result.OutputDirectory, job.OutputDir) {
					return fmt.Errorf("DAW_PROTOCOL: output mismatch")
				}
				for _, p := range []string{result.Chart, result.MIDI, result.FallbackMIDI} {
					if p != "" {
						if _, e := dawResultPath(job.OutputDir, p); e != nil {
							return e
						}
					}
				}
				if result.Status != "complete" && result.Status != "midi_only" && result.Status != "cancelled" {
					return fmt.Errorf("DAW_PROTOCOL: unexpected result")
				}
				if event.Type == "cancelled" {
					result.Status = "cancelled"
					s.appendDawLog(job, event.Message, "warning")
				}
				job.Result = &result
				_ = input.Close()
				job.input = nil
			}
			return nil
		})
	}
	if e != nil {
		cancel()
	}
	exitErr := cmd.Wait()
	if e == nil {
		e = exitErr
	}
	if e != nil && stderr.String() != "" {
		e = fmt.Errorf("DAW_ENGINE: %v\n%s", e, stderr.String())
	}
	s.finishDaw(job, e)
}
func (s *EditorService) finishDaw(job *DawJob, err error) {
	s.dawMu.Lock()
	defer s.dawMu.Unlock()
	job.input = nil
	if err != nil {
		job.Status = "error"
		job.Error = err.Error()
		s.appendDawLog(job, job.Error, "error")
		return
	}
	if job.Result == nil {
		job.Status = "error"
		job.Error = "DAW_PROTOCOL: missing result"
		return
	}
	job.Status = job.Result.Status
	if job.CancelRequested {
		job.Status = "cancelled"
	}
}
func (s *EditorService) DawCancel(id string) error {
	s.dawMu.Lock()
	defer s.dawMu.Unlock()
	job := s.dawJob
	if job == nil || job.ID != id {
		return fmt.Errorf("DAW_INPUT: unknown job")
	}
	if job.Status != "running" {
		return nil
	}
	if job.CancelRequested {
		return nil
	}
	job.CancelRequested = true
	if job.input != nil {
		_, e := io.WriteString(job.input, "{\"action\":\"cancel\"}\n")
		return e
	}
	return nil
}
func dawResultPath(root, relative string) (string, error) {
	if filepath.IsAbs(relative) || filepath.VolumeName(relative) != "" {
		return "", fmt.Errorf("DAW_PROTOCOL: absolute result path")
	}
	path := filepath.Join(root, relative)
	rel, e := filepath.Rel(root, path)
	if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) || rel == "." {
		return "", fmt.Errorf("DAW_PROTOCOL: result path escapes output")
	}
	return path, nil
}
func (s *EditorService) DawOpenResult(id string) (*chart.Document, error) {
	s.dawMu.Lock()
	job := cloneDawJob(s.dawJob)
	s.dawMu.Unlock()
	if job == nil || job.ID != id || job.Status != "complete" || job.Result == nil || job.Result.Chart == "" {
		return nil, fmt.Errorf("DAW_INPUT: no completed chart")
	}
	path, e := dawResultPath(job.OutputDir, job.Result.Chart)
	if e != nil {
		return nil, e
	}
	resolved, e := filepath.EvalSymlinks(path)
	if e != nil {
		return nil, e
	}
	root, e := filepath.EvalSymlinks(job.OutputDir)
	if e != nil {
		return nil, e
	}
	rel, e := filepath.Rel(root, resolved)
	if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return nil, fmt.Errorf("DAW_PROTOCOL: result link escapes output")
	}
	return s.Open(resolved, "Auto")
}
func (s *EditorService) DawOpenOutput(id string) error {
	s.dawMu.Lock()
	job := cloneDawJob(s.dawJob)
	s.dawMu.Unlock()
	if job == nil || job.ID != id {
		return fmt.Errorf("DAW_INPUT: unknown job")
	}
	if info, e := os.Stat(job.OutputDir); e != nil || !info.IsDir() {
		return fmt.Errorf("DAW_INPUT: output is not available yet")
	}
	return s.OpenDirectory(filepath.Join(job.OutputDir, "conversion.json"))
}
