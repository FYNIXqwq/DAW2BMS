package chart

import (
	"reflect"
	"strings"
	"testing"
)

func TestRoundTripExtensions(t *testing.T) {
	text := `#TITLE Test 日本語
#BASE 62
#BPM 130
#WAV01 kick.wav
#WAVzz piano.ogg
#BMP01 cover.png
#BPM0a 150.25
#STOP01 48
#SCROLL01 0
#SPEED01 -2
#00102:0.75
#00111:zz0001000000
#00151:0101
#001D1:0Z00
#00108:0a
#00109:01
#001SC:01
#001SP:01
#00101:01
#001ZZ:abcd
#CUSTOM hello
`
	d, e := Parse(text)
	if e != nil {
		t.Fatal(e)
	}
	serialized, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := Parse(serialized)
	if e != nil {
		t.Fatal(e)
	}
	if d.Base != 62 || r.WAV["3843"] != "piano.ogg" || r.Measures[1] != .75 {
		t.Fatalf("metadata lost: %#v", r)
	}
	for _, n := range d.Notes {
		found := false
		for _, m := range r.Notes {
			if n.Channel == m.Channel && n.Measure == m.Measure && n.Kind == m.Kind && n.Value == m.Value && n.Position == m.Position {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("lost note %+v", n)
		}
	}
	if !strings.Contains(serialized, "#CUSTOM hello") || !strings.Contains(serialized, "#001ZZ:abcd") {
		t.Fatal("unknown data lost")
	}
}

func TestSerializeDoesNotMutate(t *testing.T) {
	d, e := Parse("#BPM 130\n#BPM01 150.5\n#00008:01\n#00051:0101")
	if e != nil {
		t.Fatal(e)
	}
	before := append([]Note(nil), d.Notes...)
	if _, e = Serialize(d); e != nil {
		t.Fatal(e)
	}
	if !reflect.DeepEqual(before, d.Notes) {
		t.Fatal("serialization changed live notes")
	}
	d.Notes = append(d.Notes, Note{ID: "bad", Measure: 1000, Channel: 8, Value: 120})
	before = append([]Note(nil), d.Notes...)
	if _, e = Serialize(d); e == nil {
		t.Fatal("expected invalid measure")
	}
	if !reflect.DeepEqual(before, d.Notes) {
		t.Fatal("failed serialization changed notes")
	}
}

func TestPositionsAndOverlap(t *testing.T) {
	d := New()
	d.Notes = []Note{{ID: "a", Measure: 0, Channel: 37, Kind: "normal", Value: 1, Position: 1.0 / 7, Numerator: 1, Denominator: 7}, {ID: "b", Measure: 0, Channel: 37, Kind: "normal", Value: 2, Position: 1.0 / 7, Numerator: 1, Denominator: 7}}
	s, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := Parse(s)
	if e != nil {
		t.Fatal(e)
	}
	if len(r.Notes) != 2 || r.Notes[0].Position != 1.0/7 || r.Notes[1].Value != 2 {
		t.Fatalf("overlap or exact fraction lost: %+v", r.Notes)
	}
}

func TestFreshSpeedDefinitions(t *testing.T) {
	if _, e := Parse("#SPEED01 2\n#000SP:01"); e != nil {
		t.Fatal(e)
	}
	if _, e := Parse("#000SP:01"); e == nil {
		t.Fatal("undefined SPEED inherited from prior parse")
	}
}
func TestConditionalPreserved(t *testing.T) {
	raw := "#RANDOM 2\n#IF 1\n#WAV01 one.wav\n#00111:01\n#IF 2\n#00112:01\n#ENDIF\n#ENDIF\n#ENDRANDOM"
	d, e := Parse(raw + "\n#00211:01")
	if e != nil {
		t.Fatal(e)
	}
	if len(d.Notes) != 1 || d.Notes[0].Measure != 2 {
		t.Fatalf("conditional interpreted as regular notes: %+v", d.Notes)
	}
	s, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	if !strings.Contains(strings.ReplaceAll(s, "\r\n", "\n"), raw) {
		t.Fatal("conditional block changed")
	}
}
func TestCapacity(t *testing.T) {
	d := New()
	d.Base = 16
	for i := 1; i <= 256; i++ {
		d.Notes = append(d.Notes, Note{ID: "e", Measure: i, Position: 0, Channel: 9, Value: float64(i), Kind: "normal"})
	}
	if _, e := Serialize(d); e == nil {
		t.Fatal("expected capacity rejection")
	}
}
func TestInvalidInput(t *testing.T) {
	for _, text := range []string{"#00011:010", "#00002:-1", "#BASE 15", "#00008:01"} {
		if _, e := Parse(text); e == nil {
			t.Errorf("accepted malformed input: %s", text)
		}
	}
}
func TestEncodings(t *testing.T) {
	for _, enc := range []string{"UTF-8", "Shift-JIS", "UTF-16LE", "UTF-16BE", "UTF-32LE", "UTF-32BE"} {
		text := "#TITLE 日本語\r\n#00011:01\r\n"
		b, e := Encode(text, enc)
		if e != nil {
			t.Fatal(e)
		}
		r, _, e := Decode(b, enc)
		if e != nil || r != text {
			t.Fatalf("%s round trip %q %v", enc, r, e)
		}
	}
	if _, e := Encode("#TITLE 🐱", "Shift-JIS"); e == nil {
		t.Fatal("unencodable character silently replaced")
	}
}
func TestBase62Case(t *testing.T) {
	u, _ := DecodeID("AZ", 62)
	l, _ := DecodeID("Az", 62)
	if u == l || EncodeID(l, 62) != "Az" {
		t.Fatal("base62 case lost")
	}
}

func TestBGMLaneGapsSurviveSave(t *testing.T) {
	d := New()
	d.Notes = []Note{{ID: "b", Measure: 0, Channel: BGMLane + 3, Value: 1, Kind: "normal"}, {ID: "c", Measure: 2, Channel: BGMLane + 1, Value: 2, Kind: "normal"}}
	s, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := Parse(s)
	if e != nil {
		t.Fatal(e)
	}
	if len(r.Notes) != 2 || r.Notes[0].Channel != BGMLane+3 || r.Notes[1].Channel != BGMLane+1 {
		t.Fatalf("BGM layout shifted: %+v", r.Notes)
	}
}
func TestInvalidHeaderBPM(t *testing.T) {
	for _, bpm := range []string{"NaN", "0", "-1", "+Inf", "abc"} {
		d := New()
		d.Headers["BPM"] = bpm
		if _, e := Serialize(d); e == nil {
			t.Errorf("accepted invalid BPM %q", bpm)
		}
	}
}
