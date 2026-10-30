package chart

import (
	"bufio"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
)

var objectLine = regexp.MustCompile(`^#([0-9]{3})([0-9A-Za-z]{2}):(.*)$`)
var definition = regexp.MustCompile(`(?i)^#(WAV|BMP|BGA|BPM|STOP|SCROLL|SPEED)([0-9A-Za-z]{2})\s+(.*)$`)
var headerNames = strings.Fields("PLAYER GENRE TITLE SUBTITLE ARTIST SUBARTIST BPM PLAYLEVEL RANK TOTAL VOLWAV STAGEFILE BANNER BACKBMP PREVIEW DIFFICULTY LNOBJ LNMODE LNTYPE DEFEXRANK COMMENT OCT/FP")

func Parse(text string) (Document, error) {
	d := New()
	if len(text) > 32<<20 {
		return d, fmt.Errorf("chart exceeds 32 MiB")
	}
	text, draftData := splitDawDraft(text)
	lines := strings.Split(strings.ReplaceAll(strings.ReplaceAll(strings.TrimPrefix(text, "\ufeff"), "\r\n", "\n"), "\r", "\n"), "\n")
	lnType2 := false
	segments := []lnSegment{}
	depth := 0
	for _, raw := range lines {
		l := strings.TrimSpace(raw)
		fields := strings.Fields(l)
		if len(fields) == 0 {
			continue
		}
		cmd := strings.ToUpper(fields[0])
		if cmd == "#GENLE" {
			cmd = "#GENRE"
		}
		if cmd == "#RANDOM" || cmd == "#RONDAM" || cmd == "#SETSWITCH" || cmd == "#SETRANDOM" || cmd == "#IF" || cmd == "#SWITCH" {
			depth++
			continue
		}
		if cmd == "#ENDRANDOM" || cmd == "#ENDIF" || cmd == "#ENDSW" || cmd == "#ENDSWITCH" {
			if depth > 0 {
				depth--
			}
			continue
		}
		if depth == 0 && cmd == "#LNTYPE" && len(fields) > 1 && fields[1] == "2" {
			lnType2 = true
		}
		if depth == 0 && cmd == "#BASE" && len(fields) > 1 {
			b, e := strconv.Atoi(fields[1])
			if e != nil || b != 16 && b != 36 && b != 62 {
				return d, fmt.Errorf("invalid #BASE %s", fields[1])
			}
			d.Base = b
		}
		if depth == 0 && cmd == "#LNTYPE" && len(fields) > 1 {
			lnType2 = fields[1] == "2"
		}
	}
	defs := map[int]map[int]float64{8: {}, 9: {}, 1020: {}, 1033: {}}
	bgm := map[int]int{}
	depth = 0
	randomDepth := 0
	conditionalWarn := false
	for lineNo, raw := range lines {
		l := strings.TrimSpace(raw)
		if l == "" {
			continue
		}
		fields := strings.Fields(l)
		cmd := strings.ToUpper(fields[0])
		if cmd == "#GENLE" {
			cmd = "#GENRE"
		}
		if cmd == "#RANDOM" || cmd == "#RONDAM" || cmd == "#SETSWITCH" || cmd == "#SETRANDOM" || cmd == "#SWITCH" {
			randomDepth++
		}
		if cmd == "#IF" {
			depth++
		}
		if depth > 0 || randomDepth > 0 || cmd == "#ENDIF" || cmd == "#ENDRANDOM" || cmd == "#ENDSW" || cmd == "#ENDSWITCH" {
			d.Extra = append(d.Extra, raw)
			if !conditionalWarn {
				d.Warnings = append(d.Warnings, "条件分支已原样保留在扩展定义中，不在画布上展开。")
				conditionalWarn = true
			}
			if cmd == "#ENDIF" && depth > 0 {
				depth--
			}
			if (cmd == "#ENDRANDOM" || cmd == "#ENDSW" || cmd == "#ENDSWITCH") && randomDepth > 0 {
				randomDepth--
			}
			continue
		}
		if cmd == "#BASE" {
			continue
		}
		if m := objectLine.FindStringSubmatch(l); m != nil {
			measure, _ := strconv.Atoi(m[1])
			channel, e := DecodeID(m[2], 36)
			if e != nil {
				return d, e
			}
			data := strings.TrimSpace(m[3])
			if channel == 2 {
				v, e := strconv.ParseFloat(data, 64)
				if e != nil || math.IsNaN(v) || math.IsInf(v, 0) || v <= 0 || v > 512 {
					return d, fmt.Errorf("line %d: invalid measure length", lineNo+1)
				}
				d.Measures[measure] = v
				continue
			}
			kind := "normal"
			c := channel
			if KeyChannel(c - 432) {
				kind = "mine"
				c -= 432
			} else if KeyChannel(c - 144) {
				kind = "long"
				c -= 144
			} else if KeyChannel(c - 72) {
				kind = "invisible"
				c -= 72
			}
			if channel == 1 {
				c = BGMLane + bgm[measure]
				bgm[measure]++
				if bgm[measure] > 128 {
					return d, fmt.Errorf("line %d: more than 128 BGM lanes", lineNo+1)
				}
			}
			if !MaterialChannel(c) && !EventChannel(c) && c != 3 {
				d.Extra = append(d.Extra, raw)
				continue
			}
			if len(data)%2 != 0 {
				return d, fmt.Errorf("line %d: object data must contain pairs", lineNo+1)
			}
			for p := 0; p < len(data)/2; p++ {
				token := data[p*2 : p*2+2]
				if token == "00" {
					continue
				}
				if len(d.Notes)+len(segments) >= 200000 {
					return d, fmt.Errorf("chart exceeds the 200000-object editing limit")
				}
				base := d.Base
				if c == 3 {
					base = 16
				}
				if kind == "mine" {
					base = 36
				}
				v, e := DecodeID(token, base)
				if e != nil {
					return d, fmt.Errorf("line %d: %w", lineNo+1, e)
				}
				if lnType2 && kind == "long" {
					segments = append(segments, lnSegment{float64(measure) + float64(p)/float64(len(data)/2), float64(measure) + float64(p+1)/float64(len(data)/2), c, float64(v)})
					continue
				}
				d.Notes = append(d.Notes, Note{ID: fmt.Sprintf("n%d", len(d.Notes)+1), Measure: measure, Position: float64(p) / float64(len(data)/2), Numerator: p, Denominator: len(data) / 2, Channel: c, Kind: kind, Value: float64(v)})
			}
			continue
		}
		if m := definition.FindStringSubmatch(l); m != nil {
			id, e := DecodeID(m[2], d.Base)
			if e != nil {
				return d, e
			}
			key := strconv.Itoa(id)
			name := strings.ToUpper(m[1])
			switch name {
			case "WAV":
				d.WAV[key] = m[3]
			case "BMP":
				d.BMP[key] = m[3]
			case "BGA":
				d.BGA[key] = m[3]
			default:
				v, e := strconv.ParseFloat(strings.TrimSpace(m[3]), 64)
				if e != nil || math.IsNaN(v) || math.IsInf(v, 0) {
					return d, fmt.Errorf("line %d: invalid %s definition", lineNo+1, name)
				}
				c := map[string]int{"BPM": 8, "STOP": 9, "SCROLL": 1020, "SPEED": 1033}[name]
				defs[c][id] = v
			}
			continue
		}
		known := false
		for _, h := range headerNames {
			if cmd == "#"+h {
				d.Headers[h] = strings.TrimSpace(strings.TrimPrefix(l, fields[0]))
				if h == "OCT/FP" && d.Headers[h] == "" {
					d.Headers[h] = "1"
				}
				known = true
				break
			}
		}
		if !known && !strings.HasPrefix(l, "*----------------------") {
			d.Extra = append(d.Extra, raw)
		}
	}
	d.Definitions = defs
	for i := range d.Notes {
		n := &d.Notes[i]
		if n.Channel == 3 {
			n.Channel = 8
			continue
		}
		if EventChannel(n.Channel) {
			v, ok := defs[n.Channel][int(n.Value)]
			if !ok {
				return d, fmt.Errorf("measure %03d: undefined %s%s", n.Measure, EncodeID(n.Channel, 36), EncodeID(int(n.Value), d.Base))
			}
			n.Value = v
		}
	}
	if lnType2 {
		if e := normalizeLN2(&d, segments); e != nil {
			return d, e
		}
	}
	RememberSource(&d, text)
	if e := restoreDawDraft(&d, text, draftData); e != nil {
		d.Warnings = append(d.Warnings, "DAW_DRAFT_INVALID: "+e.Error())
	}
	return d, nil
}

func ParseReader(s *bufio.Scanner) (Document, error) {
	s.Buffer(make([]byte, 4096), 16<<20)
	var b strings.Builder
	for s.Scan() {
		b.WriteString(s.Text())
		b.WriteByte('\n')
		if b.Len() > 32<<20 {
			return New(), fmt.Errorf("chart exceeds 32 MiB")
		}
	}
	if e := s.Err(); e != nil {
		return New(), e
	}
	return Parse(b.String())
}
