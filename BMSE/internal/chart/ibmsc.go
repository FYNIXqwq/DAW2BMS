package chart

// Format reference: zardoru/iBMSC ChartIO.vb and Editor.Note.WriteBinWriter.
// This reader is bounded and rejects unknown blocks instead of guessing their layout.
import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"
	"unicode/utf16"
)

type ibReader struct {
	*bytes.Reader
	err error
}

func (r *ibReader) read(v any) {
	if r.err == nil {
		r.err = binary.Read(r.Reader, binary.LittleEndian, v)
	}
}
func (r *ibReader) i32() int     { var v int32; r.read(&v); return int(v) }
func (r *ibReader) i16() int     { var v int16; r.read(&v); return int(v) }
func (r *ibReader) i64() int64   { var v int64; r.read(&v); return v }
func (r *ibReader) byte() byte   { var v byte; r.read(&v); return v }
func (r *ibReader) f64() float64 { var v float64; r.read(&v); return v }
func (r *ibReader) skip(n int) {
	if n < 0 || n > r.Len() {
		r.err = io.ErrUnexpectedEOF
		return
	}
	if r.err == nil {
		_, r.err = r.Seek(int64(n), io.SeekCurrent)
	}
}
func (r *ibReader) str() string {
	length := 0
	for i := 0; i < 5; i++ {
		b := r.byte()
		length |= int(b&127) << (7 * i)
		if b < 128 {
			if length > 4<<20 || length%2 != 0 || length > r.Len() {
				r.err = fmt.Errorf("invalid UTF-16 string length")
				return ""
			}
			buf := make([]byte, length)
			if r.err == nil {
				_, r.err = io.ReadFull(r.Reader, buf)
			}
			words := make([]uint16, length/2)
			for i := range words {
				words[i] = binary.LittleEndian.Uint16(buf[i*2:])
			}
			return string(utf16.Decode(words))
		}
	}
	r.err = fmt.Errorf("invalid string prefix")
	return ""
}
func IBMSCChannel(index int, extended bool) int {
	if extended {
		m := map[int]int{1: 1020, 2: 8, 3: 9, 5: 42, 7: 37, 8: 38, 9: 39, 10: 40, 11: 41, 12: 44, 13: 45, 32: 73, 33: 74, 34: 75, 35: 76, 36: 77, 37: 80, 38: 81, 57: 78, 59: 4, 60: 7, 61: 6}
		if index >= 63 && index < 63+128 {
			return BGMLane + index - 63
		}
		return m[index]
	}
	m := map[int]int{1: 1020, 2: 8, 3: 9, 5: 42, 6: 37, 7: 38, 8: 39, 9: 40, 10: 41, 11: 44, 12: 45, 14: 73, 15: 74, 16: 75, 17: 76, 18: 77, 19: 80, 20: 81, 21: 78, 23: 4, 24: 7, 25: 6}
	if index >= 27 && index < 27+128 {
		return BGMLane + index - 27
	}
	return m[index]
}

func ParseIBMSC(data []byte, extended bool) (Document, error) {
	d := New()
	if len(data) < 8 || len(data) > 32<<20 || string(data[:5]) != "iBMSC" {
		return d, fmt.Errorf("not a supported iBMSC project")
	}
	if data[5] != 3 {
		return d, fmt.Errorf("unsupported iBMSC major version %d", data[5])
	}
	r := &ibReader{Reader: bytes.NewReader(data[8:])}
	nt := false
	type sourceNote struct {
		position, length, value float64
		column                  int
		long, hidden, mine      bool
	}
	notes := []sourceNote{}
	count := func(max int) int {
		n := r.i32()
		if n < 0 || n > max {
			r.err = fmt.Errorf("iBMSC block count out of bounds")
			return 0
		}
		return n
	}
	for r.Len() > 0 && r.err == nil {
		block := r.i32()
		switch block {
		case 0x66657250:
			flags := r.i32()
			nt = flags&1 != 0
			r.skip(24)
		case 0x64616548:
			for _, k := range []string{"TITLE", "ARTIST", "GENRE"} {
				d.Headers[k] = r.str()
			}
			d.Headers["BPM"] = number(float64(r.i64()) / 10000)
			flags := r.byte()
			d.Headers["PLAYER"] = strconv.Itoa(int(flags&15) + 1)
			d.Headers["RANK"] = strconv.Itoa(int(flags >> 4))
			d.Headers["PLAYLEVEL"] = r.str()
			for _, k := range []string{"SUBTITLE", "SUBARTIST", "STAGEFILE", "BANNER", "BACKBMP"} {
				d.Headers[k] = r.str()
			}
			d.Headers["DIFFICULTY"] = strconv.Itoa(int(r.byte()))
			for _, k := range []string{"DEFEXRANK", "TOTAL", "COMMENT"} {
				d.Headers[k] = r.str()
			}
			if id := r.i16(); id > 0 {
				d.Headers["LNOBJ"] = EncodeID(id, 36)
			}
		case 0x564157, 0x504D42:
			table := d.BMP
			if block == 0x564157 {
				r.byte()
				table = d.WAV
			}
			n := count(3844)
			for i := 0; i < n && r.err == nil; i++ {
				id := r.i16()
				s := r.str()
				if id < 0 || id > 3843 {
					r.err = fmt.Errorf("invalid material index")
				} else {
					table[strconv.Itoa(id)] = s
					if id > 1295 {
						d.Base = 62
					}
				}
			}
		case 0x74616542:
			r.skip(5)
			n := count(1000)
			for i := 0; i < n && r.err == nil; i++ {
				m := r.i16()
				length := r.f64()
				if m < 0 || m > 999 || math.IsNaN(length) || math.IsInf(length, 0) || length <= 0 || length > 192*512 {
					r.err = fmt.Errorf("invalid iBMSC measure")
				} else {
					d.Measures[m] = length / 192
				}
			}
		case 0x6E707845:
			d.Extra = append(d.Extra, strings.Split(strings.ReplaceAll(r.str(), "\r", ""), "\n")...)
		case 0x65746F4E:
			n := count(200000)
			for i := 0; i < n && r.err == nil; i++ {
				note := sourceNote{}
				note.position = r.f64()
				note.column = r.i32()
				note.value = float64(r.i64()) / 10000
				note.long = r.byte() != 0
				note.length = r.f64()
				note.hidden = r.byte() != 0
				note.mine = r.byte() != 0
				notes = append(notes, note)
			}
		case 0x6F646E55:
			n := count(1000)
			r.i32()
			for i := 0; i < n && r.err == nil; i++ {
				for side := 0; side < 2; side++ {
					entries := count(200000)
					for j := 0; j < entries && r.err == nil; j++ {
						r.skip(count(32 << 20))
					}
				}
			}
		default:
			return d, fmt.Errorf("unsupported iBMSC block 0x%08x", block)
		}
	}
	if r.err != nil {
		return d, fmt.Errorf("invalid/truncated iBMSC file: %w", r.err)
	}
	starts := make([]float64, 1001)
	for m := 0; m < 1000; m++ {
		ratio := d.Measures[m]
		if ratio == 0 {
			ratio = 1
		}
		starts[m+1] = starts[m] + 192*ratio
	}
	add := func(t float64, ch int, kind string, value float64) error {
		if math.IsNaN(t) || math.IsInf(t, 0) || t < 0 || t >= starts[1000] {
			return fmt.Errorf("iBMSC note is outside supported measures")
		}
		m := 0
		for m < 999 && starts[m+1] <= t {
			m++
		}
		d.Notes = append(d.Notes, Note{ID: fmt.Sprintf("ib-%d", len(d.Notes)+1), Measure: m, Position: (t - starts[m]) / (starts[m+1] - starts[m]), Channel: ch, Kind: kind, Value: value})
		return nil
	}
	for _, n := range notes {
		ch := IBMSCChannel(n.column, extended)
		if ch == 0 {
			return d, fmt.Errorf("unsupported iBMSC column %d; select the matching 27/63 column layout", n.column)
		}
		kind := "normal"
		if n.hidden {
			kind = "invisible"
		} else if n.mine {
			kind = "mine"
		} else if nt && n.length > 0 || !nt && n.long {
			kind = "long"
		}
		if e := add(n.position, ch, kind, n.value); e != nil {
			return d, e
		}
		if nt && kind == "long" {
			if e := add(n.position+n.length, ch, kind, n.value); e != nil {
				return d, e
			}
		}
	}
	d.Warnings = append(d.Warnings, "已导入 iBMSC 谱面数据；编辑历史和该编辑器的界面设置不导入，保存时另存为 BMS。")
	if opaqueExtra(d) {
		plain := d
		plain.Extra = nil
		body, e := Serialize(plain)
		if e != nil {
			return d, e
		}
		RememberSource(&d, body+"\n"+strings.Join(d.Extra, "\n"))
	}
	return d, nil
}
