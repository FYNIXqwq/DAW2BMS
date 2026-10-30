package chart

import (
	"bytes"
	"encoding/binary"
	"math"
	"strings"
	"testing"
	"unicode/utf16"
)

func TestResolveNestedBranches(t *testing.T) {
	source := "#BPM 130\n#RANDOM 2\n#IF 1\n#00111:01\n#ELSE\n#SETRANDOM 2\n#IF 2\n#00212:02\n#ENDIF\n#ENDRANDOM\n#ENDIF\n#ENDRANDOM"
	choices := Branches(source)
	if len(choices) != 2 {
		t.Fatal(choices)
	}
	d, e := ResolveBranches(source, map[int]int{2: 2})
	if e != nil || len(d.Notes) != 1 || d.Notes[0].Channel != 38 || d.Notes[0].Measure != 2 {
		t.Fatal("wrong branch", d.Notes, e)
	}
	original, e := Parse(source)
	if e != nil || len(original.Notes) != 0 {
		t.Fatal("original changed", e)
	}
}

func TestHorizontalDuplicateAndBGAReferenceIsolation(t *testing.T) {
	d := New()
	d.BGA["1"] = "01 0 0 256 256 0 0"
	d.Notes = []Note{{ID: "a", Channel: 37, Kind: "normal", Value: 1}, {ID: "b", Channel: BGMLane, Kind: "normal", Value: 1}}
	foundDuplicate, foundMissing := false, false
	for _, i := range Validate(d) {
		if i.Message == "同音素材在同一时间跨轨道重复" {
			foundDuplicate = true
		}
		if strings.Contains(i.Message, "未定义的素材") {
			foundMissing = true
		}
	}
	if !foundDuplicate || !foundMissing {
		t.Fatal("missing audio diagnostics")
	}
}
func TestResolveSwitchAndInvalidRange(t *testing.T) {
	s := "#SWITCH 2\n#CASE 1\n#00011:01\n#SKIP\n#CASE 2\n#00012:02\n#SKIP\n#ENDSW"
	d, e := ResolveBranches(s, map[int]int{1: 2})
	if e != nil || len(d.Notes) != 1 || d.Notes[0].Channel != 38 {
		t.Fatal(d.Notes, e)
	}
	if _, e = ResolveBranches(s, map[int]int{1: 3}); e == nil {
		t.Fatal("invalid choice accepted")
	}
}
func TestLNTYPE2AcrossMeasures(t *testing.T) {
	d, e := Parse("#LNTYPE 2\n#00051:00010101\n#00151:01010000\n#00102:0.75")
	if e != nil {
		t.Fatal(e)
	}
	if d.Headers["LNTYPE"] != "1" || len(d.Notes) != 2 || d.Notes[0].Position != .25 || d.Notes[1].Measure != 1 || d.Notes[1].Position != .5 {
		t.Fatalf("wrong MGQ interval %+v", d.Notes)
	}
	s, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := Parse(s)
	if e != nil || len(r.Notes) != 2 {
		t.Fatal(e)
	}
}
func TestLNOBJAndOverlapValidation(t *testing.T) {
	d, e := Parse("#LNOBJ ZZ\n#00011:ZZ\n#00151:0101\n#00111:00010000")
	if e != nil {
		t.Fatal(e)
	}
	issues := Validate(d)
	foundMarker, foundInside := false, false
	for _, i := range issues {
		if i.Message == "LNOBJ 缺少有效起点" {
			foundMarker = true
		}
		if i.Message == "长音符区间内存在其他可见对象" {
			foundInside = true
		}
	}
	if !foundMarker || !foundInside {
		t.Fatal(issues)
	}
}
func ibFixture() []byte {
	var b bytes.Buffer
	b.Write([]byte{'i', 'B', 'M', 'S', 'C', 3, 3, 0})
	write := func(v any) { _ = binary.Write(&b, binary.LittleEndian, v) }
	str := func(s string) {
		u := utf16.Encode([]rune(s))
		n := len(u) * 2
		for n >= 128 {
			b.WriteByte(byte(n) | 128)
			n >>= 7
		}
		b.WriteByte(byte(n))
		for _, c := range u {
			write(c)
		}
	}
	write(int32(0x66657250))
	write(int32(1))
	b.Write(make([]byte, 24))
	write(int32(0x64616548))
	str("Test 日本語")
	str("Author")
	str("Genre")
	write(int64(1300000))
	b.WriteByte(0x20)
	str("5")
	for i := 0; i < 5; i++ {
		str("")
	}
	b.WriteByte(0)
	str("")
	str("160")
	str("")
	write(int16(0))
	write(int32(0x564157))
	b.WriteByte(0)
	write(int32(1))
	write(int16(1))
	str("kick.wav")
	write(int32(0x65746F4E))
	write(int32(1))
	write(float64(48))
	write(int32(6))
	write(int64(10000))
	b.WriteByte(0)
	write(float64(96))
	b.WriteByte(0)
	b.WriteByte(0)
	return b.Bytes()
}
func TestIBMSCProjectImport(t *testing.T) {
	data := ibFixture()
	d, e := ParseIBMSC(data, false)
	if e != nil {
		t.Fatal(e)
	}
	if d.Headers["TITLE"] != "Test 日本語" || d.Headers["BPM"] != "130" || len(d.Notes) != 2 || d.Notes[0].Channel != 37 || math.Abs(d.Notes[1].Position-.75) > 1e-10 {
		t.Fatal(d)
	}
	for _, n := range []int{0, 4, 10, len(data) - 1} {
		if _, e = ParseIBMSC(data[:n], false); e == nil {
			t.Fatal("truncated project accepted", n)
		}
	}
}
