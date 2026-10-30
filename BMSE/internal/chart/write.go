package chart

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// Serialize never changes its argument, including on validation failure.
func Serialize(d Document) (string, error) {
	if d.SourceText != "" {
		if !sourceMatches(d) {
			return "", fmt.Errorf("条件谱面的可视化修改不能安全写回原分支；请撤销修改后使用 BMS 文本编辑，或展开为独立谱面")
		}
		return d.SourceText, nil
	}
	if opaqueExtra(d) {
		return "", fmt.Errorf("条件谱面缺少原始源文，请重新打开原文件或使用 BMS 文本编辑")
	}
	if len(d.Notes) > 200000 {
		return "", fmt.Errorf("chart exceeds 200000 objects")
	}
	if d.Base != 16 && d.Base != 36 && d.Base != 62 {
		return "", fmt.Errorf("invalid base")
	}
	bpm, err := strconv.ParseFloat(d.Headers["BPM"], 64)
	if err != nil || math.IsNaN(bpm) || math.IsInf(bpm, 0) || bpm <= 0 {
		return "", fmt.Errorf("header BPM must be a positive number")
	}
	if s := d.Headers["LNOBJ"]; s != "" {
		v, e := DecodeID(s, d.Base)
		if e != nil || len(s) != 2 || v == 0 {
			return "", fmt.Errorf("invalid LNOBJ")
		}
	}
	for m := range d.Measures {
		if m < 0 || m > 999 {
			return "", fmt.Errorf("invalid measure index %d", m)
		}
	}
	var out strings.Builder
	var writeErr error
	write := func(s string) {
		if writeErr != nil {
			return
		}
		if len(s)+2 > (32<<20)-out.Len() {
			writeErr = fmt.Errorf("output exceeds 32 MiB")
			return
		}
		out.WriteString(s)
		out.WriteString("\r\n")
	}
	write("*---------------------- HEADER FIELD")
	if d.Base != 36 {
		write(fmt.Sprintf("#BASE %d", d.Base))
	}
	for _, key := range headerNames {
		if v := strings.TrimSpace(d.Headers[key]); v != "" {
			if strings.ContainsAny(v, "\r\n") {
				return "", fmt.Errorf("%s must be one line", key)
			}
			write("#" + key + " " + v)
		}
	}
	write("")
	for _, table := range []struct {
		name string
		data map[string]string
	}{{"WAV", d.WAV}, {"BMP", d.BMP}, {"BGA", d.BGA}} {
		ids := []int{}
		for key, v := range table.data {
			if v == "" {
				continue
			}
			id, e := strconv.Atoi(key)
			if e != nil || id < 0 || id >= d.Base*d.Base {
				return "", fmt.Errorf("%s%s exceeds base-%d capacity", table.name, key, d.Base)
			}
			ids = append(ids, id)
		}
		sort.Ints(ids)
		for _, id := range ids {
			v := table.data[strconv.Itoa(id)]
			if strings.ContainsAny(v, "\r\n") {
				return "", fmt.Errorf("invalid multiline material")
			}
			write("#" + table.name + EncodeID(id, d.Base) + " " + v)
		}
	}
	if writeErr != nil {
		return "", writeErr
	}
	type cell struct {
		num, den int
		token    string
	}
	type group struct{ measure, channel int }
	groups := map[group][]cell{}
	defs := map[int]map[int]float64{8: {}, 9: {}, 1020: {}, 1033: {}}
	lookup := map[int]map[float64]int{8: {}, 9: {}, 1020: {}, 1033: {}}
	for ch, table := range d.Definitions {
		if !EventChannel(ch) {
			return "", fmt.Errorf("unsupported definition channel %d", ch)
		}
		for id, value := range table {
			if id < 0 || id >= d.Base*d.Base || math.IsNaN(value) || math.IsInf(value, 0) {
				return "", fmt.Errorf("invalid event definition")
			}
			defs[ch][id] = value
			if id > 0 {
				previous, ok := lookup[ch][value]
				if !ok || id < previous {
					lookup[ch][value] = id
				}
			}
		}
	}
	for _, n := range d.Notes {
		if n.Measure < 0 || n.Measure > 999 {
			return "", fmt.Errorf("note %s: invalid measure", n.ID)
		}
		num, den, e := fraction(n)
		if e != nil {
			return "", e
		}
		if math.IsNaN(n.Value) || math.IsInf(n.Value, 0) {
			return "", fmt.Errorf("note %s: invalid value", n.ID)
		}
		ch := n.Channel
		value := int(n.Value)
		base := d.Base
		if EventChannel(ch) {
			if ch == 8 && n.Value <= 0 {
				return "", fmt.Errorf("BPM must be positive")
			}
			if ch == 8 && value > 0 && value < 256 && n.Value == float64(value) {
				ch = 3
				base = 16
			} else {
				id, ok := lookup[ch][n.Value]
				if !ok {
					for id = 1; id < d.Base*d.Base; id++ {
						if _, exists := defs[ch][id]; !exists {
							break
						}
					}
					if id >= d.Base*d.Base {
						return "", fmt.Errorf("too many %s definitions", EncodeID(ch, 36))
					}
					defs[ch][id] = n.Value
					lookup[ch][n.Value] = id
				}
				value = id
			}
		}
		if KeyChannel(ch) {
			switch n.Kind {
			case "invisible":
				ch += 72
			case "long":
				ch += 144
			case "mine":
				ch += 432
				base = 36
			case "normal", "":
			default:
				return "", fmt.Errorf("invalid note kind")
			}
		}
		if !MaterialChannel(n.Channel) && !EventChannel(n.Channel) {
			return "", fmt.Errorf("unsupported channel %d", n.Channel)
		}
		if n.Channel >= BGMLane+128 {
			return "", fmt.Errorf("too many BGM lanes")
		}
		if value < 1 || value >= base*base || (!EventChannel(n.Channel) && float64(value) != n.Value) {
			return "", fmt.Errorf("measure %03d: invalid object value %g", n.Measure, n.Value)
		}
		key := group{n.Measure, ch}
		groups[key] = append(groups[key], cell{num, den, EncodeID(value, base)})
	}
	for _, ch := range []int{8, 9, 1020, 1033} {
		name := map[int]string{8: "BPM", 9: "STOP", 1020: "SCROLL", 1033: "SPEED"}[ch]
		ids := []int{}
		for id := range defs[ch] {
			ids = append(ids, id)
		}
		sort.Ints(ids)
		for _, id := range ids {
			write("#" + name + EncodeID(id, d.Base) + " " + number(defs[ch][id]))
		}
	}
	write("")
	write("*---------------------- MAIN DATA FIELD")
	keys := make([]group, 0, len(groups))
	for key := range groups {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].measure != keys[j].measure {
			return keys[i].measure < keys[j].measure
		}
		return keys[i].channel < keys[j].channel
	})
	for m := 0; m <= 999; m++ {
		if ratio, ok := d.Measures[m]; ok && ratio != 1 {
			if math.IsNaN(ratio) || math.IsInf(ratio, 0) || ratio <= 0 || ratio > 512 {
				return "", fmt.Errorf("measure %03d: invalid length", m)
			}
			write(fmt.Sprintf("#%03d02:%s", m, number(ratio)))
		}
	}
	bgmNext := map[int]int{}
	for _, key := range keys {
		cells := groups[key]
		div := 1
		for _, c := range cells {
			v := int64(div/gcd(div, c.den)) * int64(c.den)
			if v > 1920000 {
				return "", fmt.Errorf("measure %03d: required resolution exceeds 1920000; no positions were rounded", key.measure)
			}
			div = int(v)
		}
		if out.Len()+div*2+16 > 32<<20 {
			return "", fmt.Errorf("output exceeds 32 MiB")
		}
		rows := [][]byte{[]byte(strings.Repeat("00", div))}
		for _, c := range cells {
			pos := c.num * (div / c.den) * 2
			placed := false
			for _, row := range rows {
				if row[pos] == '0' && row[pos+1] == '0' {
					copy(row[pos:pos+2], c.token)
					placed = true
					break
				}
			}
			if !placed {
				if key.channel >= BGMLane {
					return "", fmt.Errorf("小节 %03d 的同一 BGM 轨道有重叠对象，请先移至不同 BGM 轨道", key.measure)
				}
				if out.Len()+(len(rows)+1)*(div*2+16) > 32<<20 {
					return "", fmt.Errorf("output exceeds 32 MiB")
				}
				row := []byte(strings.Repeat("00", div))
				copy(row[pos:pos+2], c.token)
				rows = append(rows, row)
			}
		}
		ch := key.channel
		if ch >= BGMLane {
			next := bgmNext[key.measure]
			if next == 0 {
				next = BGMLane
			}
			for lane := next; lane < ch; lane++ {
				write(fmt.Sprintf("#%03d01:00", key.measure))
			}
			bgmNext[key.measure] = ch + len(rows)
			ch = 1
		}
		for _, row := range rows {
			write(fmt.Sprintf("#%03d%s:%s", key.measure, EncodeID(ch, 36), string(row)))
		}
		if out.Len() > 32<<20 {
			return "", fmt.Errorf("output exceeds 32 MiB; reduce chart resolution")
		}
	}
	if len(d.Extra) > 0 {
		write("")
		write("*---------------------- EXTENDED FIELD")
		for _, s := range d.Extra {
			write(s)
			if out.Len() > 32<<20 {
				return "", fmt.Errorf("output exceeds 32 MiB")
			}
		}
	}
	if out.Len() > 32<<20 {
		return "", fmt.Errorf("output exceeds 32 MiB")
	}
	if writeErr != nil {
		return "", writeErr
	}
	return appendDawDraft(d, out.String())
}
