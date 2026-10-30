// Package assets implements reviewable, recoverable filesystem operations for BMS directories.
package assets

import (
	"bmse/internal/chart"
	"bmse/internal/storage"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

type Change struct {
	From string `json:"from"`
	To   string `json:"to"`
	Hash string `json:"hash"`
}
type Plan struct {
	Token     string            `json:"token"`
	Mode      string            `json:"mode"`
	Changes   []Change          `json:"changes"`
	Warnings  []string          `json:"warnings"`
	Root      string            `json:"-"`
	ChartPath string            `json:"-"`
	Before    []byte            `json:"-"`
	Checks    map[string]string `json:"-"`
	Doc       chart.Document    `json:"-"`
}
type Result struct {
	Document chart.Document `json:"document"`
	Journal  string         `json:"journal"`
	Count    int            `json:"count"`
}
type journal struct {
	Chart     string   `json:"chart"`
	AfterHash string   `json:"afterHash"`
	Changes   []Change `json:"changes"`
	Mode      string   `json:"mode"`
	Restored  bool     `json:"restored"`
	Encoding  string   `json:"encoding,omitempty"`
}

var media = map[string]bool{".wav": true, ".ogg": true, ".mp3": true, ".flac": true, ".bmp": true, ".png": true, ".jpg": true, ".jpeg": true, ".gif": true, ".webp": true, ".mp4": true, ".avi": true, ".wmv": true}
var assetLine = regexp.MustCompile(`(?i)^#(?:WAV[0-9A-Za-z]{2}|BMP[0-9A-Za-z]{2}|STAGEFILE|BANNER|BACKBMP|PREVIEW)\s+(.+)$`)

func hashFile(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	if _, e = io.Copy(h, f); e != nil {
		return "", e
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
func hashBytes(data []byte) string { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }
func safe(root, name string) (string, error) {
	if filepath.IsAbs(name) {
		return "", fmt.Errorf("absolute asset path is not editable: %s", name)
	}
	p := filepath.Join(root, filepath.FromSlash(strings.ReplaceAll(name, "\\", "/")))
	rel, e := filepath.Rel(root, p)
	if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("asset outside chart folder: %s", name)
	}
	info, e := os.Lstat(p)
	if e == nil && info.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("symbolic links cannot be modified: %s", name)
	}
	resolved, e := filepath.EvalSymlinks(filepath.Dir(p))
	if e != nil {
		return "", e
	}
	resolvedRel, e := filepath.Rel(root, resolved)
	if e != nil || resolvedRel == ".." || strings.HasPrefix(resolvedRel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("asset parent is outside chart folder")
	}
	return p, nil
}
func references(text string) map[string]bool {
	r := map[string]bool{}
	for _, line := range strings.Split(strings.ReplaceAll(text, "\r", ""), "\n") {
		m := assetLine.FindStringSubmatch(strings.TrimSpace(line))
		if m != nil {
			r[strings.ToLower(strings.ReplaceAll(strings.Trim(strings.TrimSpace(m[1]), "\""), "\\", "/"))] = true
		}
	}
	return r
}
func matches(refs map[string]bool, name string) bool {
	name = strings.ToLower(filepath.ToSlash(name))
	if refs[name] {
		return true
	}
	ext := filepath.Ext(name)
	if ext == ".wav" || ext == ".ogg" || ext == ".mp3" || ext == ".flac" {
		stem := strings.TrimSuffix(name, ext)
		for _, x := range []string{".wav", ".ogg", ".mp3", ".flac"} {
			if refs[stem+x] {
				return true
			}
		}
	}
	return false
}

func localRefs(root string, refs map[string]bool) map[string]bool {
	r := map[string]bool{}
	for name := range refs {
		p := filepath.FromSlash(name)
		if filepath.IsAbs(p) {
			rel, e := filepath.Rel(root, p)
			if e != nil {
				continue
			}
			p = rel
		}
		r[strings.ToLower(filepath.ToSlash(filepath.Clean(p)))] = true
	}
	return r
}

func Prepare(d chart.Document, mode string) (Plan, error) {
	p := Plan{Mode: mode, Changes: []Change{}, Warnings: []string{}, Checks: map[string]string{}}
	if mode != "cleanup" && mode != "rename" {
		return p, fmt.Errorf("unknown operation")
	}
	if mode == "rename" && d.SourceText != "" {
		return p, fmt.Errorf("条件源文保护模式不允许批量重命名，请先展开分支")
	}
	if d.Path == "" {
		return p, fmt.Errorf("请先保存谱面")
	}
	if strings.EqualFold(filepath.Ext(d.Path), ".ibmsc") {
		return p, fmt.Errorf("请先把 iBMSC 工程另存为 BMS")
	}
	absolute, e := filepath.Abs(d.Path)
	if e != nil {
		return p, e
	}
	root, e := filepath.EvalSymlinks(filepath.Dir(absolute))
	if e != nil {
		return p, e
	}
	p.Root = root
	p.ChartPath = filepath.Join(root, filepath.Base(absolute))
	info, e := os.Lstat(p.ChartPath)
	if e != nil || info.Mode()&os.ModeSymlink != 0 {
		return p, fmt.Errorf("chart path is not a regular local file")
	}
	p.Before, e = readChartBytes(p.ChartPath)
	if e != nil {
		return p, e
	}
	p.Checks[p.ChartPath] = hashBytes(p.Before)
	text, e := chart.Serialize(d)
	if e != nil {
		return p, e
	}
	stored, e := storage.Read(p.ChartPath, d.Encoding)
	if e != nil {
		return p, e
	}
	storedText, e := chart.Serialize(stored)
	if e != nil {
		return p, e
	}
	if text != storedText {
		return p, fmt.Errorf("请先保存当前谱面，再预览磁盘操作")
	}
	current := localRefs(root, references(text))
	shared := map[string]bool{}
	entries, e := os.ReadDir(root)
	if e != nil {
		return p, e
	}
	for _, f := range entries {
		ext := strings.ToLower(filepath.Ext(f.Name()))
		path := filepath.Join(root, f.Name())
		if f.IsDir() || strings.EqualFold(path, p.ChartPath) || !chartExtension(ext) {
			continue
		}
		data, e := readChartBytes(path)
		if e != nil {
			return p, e
		}
		if len(data) > 32<<20 {
			return p, fmt.Errorf("related chart too large: %s", f.Name())
		}
		s, _, e := chart.Decode(data, "Auto")
		if len(data) >= 5 && string(data[:5]) == "iBMSC" {
			var imported chart.Document
			imported, e = chart.ParseIBMSC(data, false)
			if e == nil {
				s, e = chart.Serialize(imported)
			}
		}
		if e != nil {
			return p, fmt.Errorf("cannot safely scan related chart %s: %w", f.Name(), e)
		}
		p.Checks[path] = hashBytes(data)
		for r := range localRefs(root, references(s)) {
			shared[r] = true
		}
	}
	bytes, _ := json.Marshal(d)
	_ = json.Unmarshal(bytes, &p.Doc)
	add := func(from, to string) error {
		path, e := safe(root, from)
		if e != nil {
			return e
		}
		h, e := hashFile(path)
		if e != nil {
			return e
		}
		p.Changes = append(p.Changes, Change{from, to, h})
		return nil
	}
	if mode == "cleanup" {
		for _, f := range entries {
			if f.IsDir() || !media[strings.ToLower(filepath.Ext(f.Name()))] || matches(current, f.Name()) || matches(shared, f.Name()) {
				continue
			}
			if e = add(f.Name(), ""); e != nil {
				return p, e
			}
		}
	} else {
		for _, line := range d.Extra {
			if regexp.MustCompile(`(?i)^\s*#(?:RANDOM|IF|SWITCH|WAV|BMP)`).MatchString(line) {
				return p, fmt.Errorf("条件分支或未解析引用存在，不能安全批量重命名")
			}
		}
		used := map[string]bool{}
		targets := map[string]bool{}
		replacements := map[string]string{}
		for _, table := range []map[string]string{d.WAV, d.BMP} {
			ids := []int{}
			for id := range table {
				n, e := strconv.Atoi(id)
				if e != nil {
					return p, e
				}
				ids = append(ids, n)
			}
			sort.Ints(ids)
			for _, id := range ids {
				name := table[strconv.Itoa(id)]
				if name == "" || used[strings.ToLower(name)] {
					continue
				}
				used[strings.ToLower(name)] = true
				if filepath.Base(name) != name || strings.ContainsAny(name, "/\\") || filepath.IsAbs(name) {
					p.Warnings = append(p.Warnings, "跳过子目录或外部路径："+name)
					continue
				}
				if matches(shared, name) {
					p.Warnings = append(p.Warnings, "其他谱面也引用，跳过："+name)
					continue
				}
				to := chart.EncodeID(id, d.Base) + strings.ToLower(filepath.Ext(name))
				if strings.EqualFold(name, to) {
					continue
				}
				if targets[strings.ToLower(to)] {
					p.Warnings = append(p.Warnings, "目标编号冲突，跳过："+name)
					continue
				}
				if _, e = os.Stat(filepath.Join(root, to)); !os.IsNotExist(e) {
					p.Warnings = append(p.Warnings, "目标已存在，跳过："+name)
					continue
				}
				if e = add(name, to); e != nil {
					return p, e
				}
				targets[strings.ToLower(to)] = true
				replacements[strings.ToLower(name)] = to
			}
		}
		for _, table := range []map[string]string{p.Doc.WAV, p.Doc.BMP} {
			for id, name := range table {
				if to, ok := replacements[strings.ToLower(name)]; ok {
					table[id] = to
				}
			}
		}
		for _, key := range []string{"STAGEFILE", "BANNER", "BACKBMP", "PREVIEW"} {
			if to, ok := replacements[strings.ToLower(p.Doc.Headers[key])]; ok {
				p.Doc.Headers[key] = to
			}
		}
	}
	id := make([]byte, 16)
	if _, e = rand.Read(id); e != nil {
		return p, e
	}
	p.Token = hex.EncodeToString(id)
	return p, nil
}

func Execute(p Plan) (Result, error) {
	result := Result{Document: p.Doc}
	if len(p.Changes) == 0 {
		return result, nil
	}
	entries, e := os.ReadDir(p.Root)
	if e != nil {
		return result, e
	}
	for _, entry := range entries {
		ext := strings.ToLower(filepath.Ext(entry.Name()))
		if !entry.IsDir() && chartExtension(ext) {
			if _, ok := p.Checks[filepath.Join(p.Root, entry.Name())]; !ok {
				return result, fmt.Errorf("预览后新增了谱面，请重新扫描共享素材")
			}
		}
	}
	for file, h := range p.Checks {
		actual, e := hashFile(file)
		if e != nil || actual != h {
			return result, fmt.Errorf("谱面在预览后改变，请重新生成操作预览")
		}
	}
	for _, c := range p.Changes {
		path, e := safe(p.Root, c.From)
		if e != nil {
			return result, e
		}
		h, e := hashFile(path)
		if e != nil || h != c.Hash {
			return result, fmt.Errorf("素材在预览后改变：%s", c.From)
		}
		if c.To != "" {
			if _, e = os.Lstat(filepath.Join(p.Root, c.To)); !os.IsNotExist(e) {
				return result, fmt.Errorf("目标已存在：%s", c.To)
			}
		}
	}
	recovery := filepath.Join(p.Root, ".bmse-recovery")
	if stat, e := os.Lstat(recovery); e == nil && stat.Mode()&os.ModeSymlink != 0 {
		return result, fmt.Errorf("recovery directory must not be a link")
	}
	if e := os.MkdirAll(recovery, 0700); e != nil {
		return result, e
	}
	dir, e := os.MkdirTemp(recovery, p.Token+"-")
	if e != nil {
		return result, e
	}
	if e = storage.AtomicWrite(filepath.Join(dir, "chart.before"), p.Before); e != nil {
		return result, e
	}
	j := journal{Chart: p.ChartPath, Mode: p.Mode, Changes: []Change{}, Encoding: p.Doc.Encoding}
	persist := func() error {
		b, _ := json.MarshalIndent(j, "", "  ")
		return storage.AtomicWrite(filepath.Join(dir, "journal.json"), b)
	}
	if e = persist(); e != nil {
		return result, e
	}
	rollback := func(cause error) (Result, error) {
		var errs []string
		for i := len(j.Changes) - 1; i >= 0; i-- {
			c := j.Changes[i]
			if e := moveNoReplace(c.To, filepath.Join(p.Root, c.From)); e != nil {
				errs = append(errs, e.Error())
			}
		}
		if len(errs) > 0 {
			return result, fmt.Errorf("%v; rollback incomplete, recovery at %s: %s", cause, dir, strings.Join(errs, "; "))
		}
		return result, cause
	}
	for _, c := range p.Changes {
		to := filepath.Join(p.Root, c.To)
		if p.Mode == "cleanup" {
			to = filepath.Join(dir, c.From)
		}
		if e = moveNoReplace(filepath.Join(p.Root, c.From), to); e != nil {
			return rollback(e)
		}
		j.Changes = append(j.Changes, Change{c.From, to, c.Hash})
		if e = persist(); e != nil {
			return rollback(e)
		}
	}
	if p.Mode == "rename" {
		if e = storage.Save(p.Doc, p.ChartPath); e != nil {
			return rollback(e)
		}
	}
	j.AfterHash, e = hashFile(p.ChartPath)
	if e != nil {
		if err := storage.AtomicWrite(p.ChartPath, p.Before); err != nil {
			return result, fmt.Errorf("%v; recovery needed at %s: %w", e, dir, err)
		}
		return rollback(e)
	}
	if e = persist(); e != nil {
		if err := storage.AtomicWrite(p.ChartPath, p.Before); err != nil {
			return result, fmt.Errorf("%v; recovery needed at %s: %w", e, dir, err)
		}
		return rollback(e)
	}
	result.Journal = filepath.Join(dir, "journal.json")
	result.Count = len(j.Changes)
	return result, nil
}

func chartExtension(ext string) bool {
	return ext == ".bms" || ext == ".bme" || ext == ".bml" || ext == ".pms" || ext == ".ibmsc"
}

func Restore(path string, expectedChart ...string) (chart.Document, error) {
	d := chart.New()
	absolute, e := filepath.Abs(path)
	if e != nil {
		return d, e
	}
	if filepath.Base(absolute) != "journal.json" || filepath.Base(filepath.Dir(filepath.Dir(absolute))) != ".bmse-recovery" {
		return d, fmt.Errorf("invalid recovery journal")
	}
	data, e := os.ReadFile(absolute)
	if e != nil {
		return d, e
	}
	var j journal
	if e = json.Unmarshal(data, &j); e != nil {
		return d, e
	}
	if len(expectedChart) > 0 {
		expected, e := filepath.Abs(expectedChart[0])
		if e != nil || !strings.EqualFold(expected, j.Chart) {
			return d, fmt.Errorf("恢复记录属于另一张谱面，请先打开对应谱面")
		}
	}
	if j.Restored {
		return d, fmt.Errorf("operation already restored")
	}
	root := filepath.Dir(filepath.Dir(filepath.Dir(absolute)))
	if filepath.Dir(j.Chart) != root {
		return d, fmt.Errorf("journal chart root mismatch")
	}
	h, e := hashFile(j.Chart)
	if e != nil || h != j.AfterHash {
		return d, fmt.Errorf("谱面已被修改，不能覆盖恢复")
	}
	for _, c := range j.Changes {
		from, e := safe(root, c.From)
		if e != nil {
			return d, e
		}
		rel, e := filepath.Rel(root, c.To)
		if e != nil || strings.HasPrefix(rel, "..") {
			return d, fmt.Errorf("invalid recovery path")
		}
		if _, e = safe(root, rel); e != nil {
			return d, e
		}
		if _, e = os.Lstat(from); !os.IsNotExist(e) {
			return d, fmt.Errorf("原文件名已被占用：%s", c.From)
		}
		h, e := hashFile(c.To)
		if e != nil || h != c.Hash {
			return d, fmt.Errorf("恢复素材已改变：%s", c.From)
		}
	}
	before, e := os.ReadFile(filepath.Join(filepath.Dir(absolute), "chart.before"))
	if e != nil {
		return d, e
	}
	done := []Change{}
	rollback := func(cause error) error {
		var errs []string
		for i := len(done) - 1; i >= 0; i-- {
			if e := moveNoReplace(filepath.Join(root, done[i].From), done[i].To); e != nil {
				errs = append(errs, e.Error())
			}
		}
		if len(errs) > 0 {
			return fmt.Errorf("%v; rollback incomplete; journal %s: %s", cause, absolute, strings.Join(errs, "; "))
		}
		return cause
	}
	for _, c := range j.Changes {
		if e = moveNoReplace(c.To, filepath.Join(root, c.From)); e != nil {
			return d, rollback(e)
		}
		done = append(done, c)
	}
	if e = storage.AtomicWrite(j.Chart, before); e != nil {
		return d, rollback(e)
	}
	j.Restored = true
	data, _ = json.MarshalIndent(j, "", "  ")
	if e = storage.AtomicWrite(absolute, data); e != nil {
		return d, e
	}
	return storage.Read(j.Chart, j.Encoding)
}

func readChartBytes(path string) ([]byte, error) {
	f, e := os.Open(path)
	if e != nil {
		return nil, e
	}
	defer f.Close()
	b, e := io.ReadAll(io.LimitReader(f, (32<<20)+1))
	if len(b) > 32<<20 {
		return nil, fmt.Errorf("chart exceeds 32 MiB")
	}
	return b, e
}
