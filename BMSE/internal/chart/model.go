package chart

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

const MaxMeasure = 999
const BGMLane = 1297
const MaxMaterial = 3843

type Note struct {
	DawOrigin   *DawOrigin `json:"dawOrigin,omitempty"`
	ID          string     `json:"id"`
	Measure     int        `json:"measure"`
	Position    float64    `json:"position"` // fraction of the measure, independent of measure length
	Numerator   int        `json:"numerator"`
	Denominator int        `json:"denominator"`
	Channel     int        `json:"channel"` // normal key channel; BGM uses 1297..1424
	Kind        string     `json:"kind"`    // normal, invisible, long, mine
	Value       float64    `json:"value"`   // material number or actual BPM/STOP/SCROLL/SPEED value
}

type Document struct {
	DawDraft    *DawDraft               `json:"dawDraft,omitempty"`
	EditorMode  string                  `json:"editorMode,omitempty"`
	Path        string                  `json:"path"`
	Encoding    string                  `json:"encoding"`
	Base        int                     `json:"base"`
	Headers     map[string]string       `json:"headers"`
	WAV         map[string]string       `json:"wav"`
	BMP         map[string]string       `json:"bmp"`
	BGA         map[string]string       `json:"bga"`
	Measures    map[int]float64         `json:"measures"`
	Notes       []Note                  `json:"notes"`
	Extra       []string                `json:"extra"`
	Warnings    []string                `json:"warnings"`
	Definitions map[int]map[int]float64 `json:"definitions,omitempty"`
	SourceText  string                  `json:"sourceText,omitempty"`
	SourceHash  string                  `json:"sourceHash,omitempty"`
}

func New() Document {
	return Document{Encoding: "UTF-8", Base: 36, Headers: map[string]string{"PLAYER": "1", "TITLE": "", "ARTIST": "", "GENRE": "", "BPM": "130", "PLAYLEVEL": "1", "RANK": "2"}, WAV: map[string]string{}, BMP: map[string]string{}, BGA: map[string]string{}, Measures: map[int]float64{}, Notes: []Note{}, Extra: []string{}, Warnings: []string{}}
}

func DecodeID(s string, base int) (int, error) {
	if base != 16 && base != 36 && base != 62 {
		return 0, fmt.Errorf("unsupported base %d", base)
	}
	if base != 62 {
		s = strings.ToUpper(s)
	}
	n := 0
	for _, c := range s {
		v := strings.IndexRune("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", c)
		if v < 0 || v >= base {
			return 0, fmt.Errorf("invalid base-%d number %q", base, s)
		}
		n = n*base + v
	}
	return n, nil
}

func EncodeID(n, base int) string {
	const digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
	if n < 0 || n >= base*base {
		return "??"
	}
	return string([]byte{digits[n/base], digits[n%base]})
}

func KeyChannel(c int) bool      { return c >= 37 && c <= 45 || c >= 73 && c <= 81 }
func EventChannel(c int) bool    { return c == 8 || c == 9 || c == 1020 || c == 1033 }
func MaterialChannel(c int) bool { return KeyChannel(c) || c >= BGMLane || c == 4 || c == 6 || c == 7 }
func number(v float64) string    { return strconv.FormatFloat(v, 'f', -1, 64) }
func gcd(a, b int) int {
	for b != 0 {
		a, b = b, a%b
	}
	if a < 0 {
		return -a
	}
	return a
}
func fraction(n Note) (int, int, error) {
	if math.IsNaN(n.Position) || math.IsInf(n.Position, 0) || n.Position < 0 || n.Position >= 1 {
		return 0, 0, fmt.Errorf("note %s: position must be in [0,1)", n.ID)
	}
	if n.Denominator > 0 && n.Denominator <= 1920000 && n.Numerator >= 0 && n.Numerator < n.Denominator && math.Abs(float64(n.Numerator)/float64(n.Denominator)-n.Position) < 1e-12 {
		g := gcd(n.Numerator, n.Denominator)
		return n.Numerator / g, n.Denominator / g, nil
	}
	x := n.Position
	h0, h1, k0, k1 := 0, 1, 1, 0
	for i := 0; i < 32; i++ {
		a := int(math.Floor(x))
		h, k := a*h1+h0, a*k1+k0
		if k > 1920000 || k <= 0 {
			break
		}
		if math.Abs(float64(h)/float64(k)-n.Position) < 1e-10 {
			return h, k, nil
		}
		h0, h1, k0, k1 = h1, h, k1, k
		rem := x - float64(a)
		if rem < 1e-14 {
			break
		}
		x = 1 / rem
	}
	return 0, 0, fmt.Errorf("note %s: position cannot be represented safely", n.ID)
}

type Issue struct {
	Severity string `json:"severity"`
	Message  string `json:"message"`
	NoteID   string `json:"noteId"`
	Measure  int    `json:"measure"`
}

func Validate(d Document) []Issue {
	r := []Issue{}
	seen := map[string]bool{}
	audioTimes := map[string]int{}
	ln := map[int][]Note{}
	for _, n := range d.Notes {
		add := func(s, m string) { r = append(r, Issue{s, m, n.ID, n.Measure}) }
		if n.Measure < 0 || n.Measure > 999 || n.Position < 0 || n.Position >= 1 {
			add("error", "音符位置超出 000–999 小节范围")
		}
		layer := "visible"
		if n.Kind == "invisible" {
			layer = "invisible"
		}
		key := fmt.Sprintf("%d/%d/%.12f/%s", n.Measure, n.Channel, n.Position, layer)
		if seen[key] {
			add("error", "同一轨道存在重叠对象")
		}
		seen[key] = true
		if (KeyChannel(n.Channel) || n.Channel >= BGMLane) && n.Kind != "mine" && n.Kind != "invisible" {
			key := fmt.Sprintf("%d/%.12f/%g", n.Measure, n.Position, n.Value)
			if ch, ok := audioTimes[key]; ok && ch != n.Channel {
				add("warning", "同音素材在同一时间跨轨道重复")
			}
			audioTimes[key] = n.Channel
		}
		if n.Kind == "long" {
			ln[n.Channel] = append(ln[n.Channel], n)
		}
		if MaterialChannel(n.Channel) && n.Kind != "mine" {
			table := d.WAV
			if n.Channel == 4 || n.Channel == 6 || n.Channel == 7 {
				table = d.BMP
			}
			id := strconv.Itoa(int(n.Value))
			isImage := n.Channel == 4 || n.Channel == 6 || n.Channel == 7
			marker, _ := DecodeID(d.Headers["LNOBJ"], d.Base)
			if table[id] == "" && !(isImage && d.BGA[id] != "") && !(KeyChannel(n.Channel) && marker > 0 && n.Value == float64(marker)) {
				add("warning", "对象引用了未定义的素材 "+EncodeID(int(n.Value), d.Base))
			}
		}
		if n.Channel == 8 && n.Value <= 0 {
			add("error", "BPM 必须大于 0")
		}
	}
	for _, notes := range ln {
		sort.Slice(notes, func(i, j int) bool {
			return float64(notes[i].Measure)+notes[i].Position < float64(notes[j].Measure)+notes[j].Position
		})
		if len(notes)%2 != 0 {
			n := notes[len(notes)-1]
			r = append(r, Issue{"error", "长音符缺少配对端点", n.ID, n.Measure})
		}
	}
	return append(r, validateLongNotes(d)...)
}
