package assets

import (
	"bmse/internal/chart"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func PrepareRename(d chart.Document, from, to string) (Plan, error) {
	p, e := Prepare(d, "cleanup")
	if e != nil {
		return p, e
	}
	if d.SourceText != "" {
		return p, fmt.Errorf("条件源文保护模式不能重命名素材")
	}
	to = strings.TrimSpace(to)
	if to == "" || filepath.Base(to) != to || strings.ContainsAny(to, `<>:"/\|?*`) || strings.HasSuffix(to, ".") {
		return p, fmt.Errorf("请填写有效的同目录文件名")
	}
	source := from
	if filepath.IsAbs(source) {
		source, e = filepath.Rel(p.Root, source)
		if e != nil {
			return p, e
		}
	}
	source = filepath.Clean(source)
	if filepath.Base(source) != source {
		return p, fmt.Errorf("仅支持谱面同目录的素材重命名")
	}
	if strings.EqualFold(source, to) {
		return p, fmt.Errorf("文件名未改变")
	}
	sourcePath, e := safe(p.Root, source)
	if e != nil {
		return p, e
	}
	if _, e = os.Stat(filepath.Join(p.Root, to)); !os.IsNotExist(e) {
		return p, fmt.Errorf("目标文件已经存在")
	}
	normalize := func(name string) string {
		if filepath.IsAbs(name) {
			if rel, e := filepath.Rel(p.Root, name); e == nil {
				name = rel
			}
		}
		return strings.ToLower(filepath.Clean(name))
	}
	matched := false
	for _, table := range []map[string]string{d.WAV, d.BMP} {
		for _, name := range table {
			if normalize(name) == strings.ToLower(source) {
				matched = true
			}
		}
	}
	if !matched {
		return p, fmt.Errorf("所选文件不是当前谱面的素材")
	}
	for file := range p.Checks {
		if strings.EqualFold(file, p.ChartPath) {
			continue
		}
		other, e := readChartBytes(file)
		if e != nil {
			return p, e
		}
		var text string
		if len(other) >= 5 && string(other[:5]) == "iBMSC" {
			project, e := chart.ParseIBMSC(other, false)
			if e != nil {
				return p, e
			}
			text, e = chart.Serialize(project)
			if e != nil {
				return p, e
			}
		} else {
			text, _, e = chart.Decode(other, "Auto")
			if e != nil {
				return p, e
			}
		}
		if matches(localRefs(p.Root, references(text)), source) {
			return p, fmt.Errorf("其他谱面也引用该文件，不能单独重命名")
		}
	}
	h, e := hashFile(sourcePath)
	if e != nil {
		return p, e
	}
	p.Mode = "rename"
	p.Changes = []Change{{From: source, To: to, Hash: h}}
	p.Warnings = []string{}
	for _, table := range []map[string]string{p.Doc.WAV, p.Doc.BMP} {
		for id, name := range table {
			if normalize(name) == strings.ToLower(source) {
				table[id] = to
			}
		}
	}
	for _, key := range []string{"STAGEFILE", "BANNER", "BACKBMP", "PREVIEW"} {
		if normalize(p.Doc.Headers[key]) == strings.ToLower(source) {
			p.Doc.Headers[key] = to
		}
	}
	return p, nil
}
