package chart

import (
	"encoding/base64"
	"math"
	"strings"
	"testing"
)

func TestAuditUnusedEventDefinitionsSurvive(t *testing.T) {
	d, e := Parse("#BPM02 150.5\n#STOPZZ 48\n#SCROLL0A -2\n#00008:02")
	if e != nil {
		t.Fatal(e)
	}
	d.Notes = append(d.Notes, Note{ID: "new", Measure: 1, Channel: 8, Kind: "normal", Value: 170.5})
	s, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	for _, line := range []string{"#BPM02 150.5", "#STOPZZ 48", "#SCROLL0A -2"} {
		if !strings.Contains(s, line) {
			t.Errorf("lost %s", line)
		}
	}
	r, e := Parse(s)
	if e != nil || r.Notes[0].Value != 150.5 || r.Notes[1].Value != 170.5 {
		t.Fatal(r.Notes, e)
	}
}

func TestAuditSystemChineseAndBOMEncodings(t *testing.T) {
	for _, item := range []struct{ enc, text string }{{"System", "ASCII title"}, {"GBK", "简体中文"}, {"Big5", "繁體中文"}, {"UTF-8 BOM", "日本語"}} {
		d := New()
		d.Headers["TITLE"] = item.text
		d.Encoding = item.enc
		encoded, e := EncodeDocument(d)
		if e != nil {
			t.Fatal(item.enc, e)
		}
		raw, _ := base64.StdEncoding.DecodeString(encoded)
		if item.enc == "UTF-8 BOM" && !strings.HasPrefix(string(raw), "\ufeff") {
			t.Fatal("BOM missing")
		}
		r, e := DecodeDocument(encoded, item.enc)
		if e != nil || r.Headers["TITLE"] != item.text {
			t.Fatal(item.enc, r.Headers, e)
		}
	}
}
func TestAuditConditionalSourceOrderAndDependencies(t *testing.T) {
	source := "#BPM01 150\n#RANDOM 2\n#IF 1\n#BPM01 160\n#00008:01\n#ENDIF\n#ENDRANDOM\n#BPM01 175\n"
	d, e := Parse(source)
	if e != nil {
		t.Fatal(e)
	}
	saved, e := Serialize(d)
	if e != nil || saved != source {
		t.Fatal("conditional source rewritten", e)
	}
	branch, e := ResolveBranches(saved, map[int]int{2: 1})
	if e != nil || len(branch.Notes) != 1 || branch.Notes[0].Value != 175 {
		t.Fatal(branch.Notes, e)
	}
	d.Headers["TITLE"] = "changed"
	if _, e = Serialize(d); e == nil {
		t.Fatal("unsafe conditional rewrite accepted")
	}
}
func TestAuditNumericInputsAreFinite(t *testing.T) {
	for _, s := range []string{"#00002:NaN", "#00002:+Inf", "#BPM01 NaN\n#00008:01", "#STOP01 -Inf"} {
		if _, e := Parse(s); e == nil {
			t.Fatal("accepted non-finite data", s)
		}
	}
}

func TestAuditLegacyGenreAlias(t *testing.T) {
	d, e := Parse("#GENLE Legacy genre\n#BPM 130")
	if e != nil || d.Headers["GENRE"] != "Legacy genre" {
		t.Fatal(d.Headers, e)
	}
}
func TestAuditBaseBeforeLNOBJ(t *testing.T) {
	d := New()
	d.Base = 62
	d.Headers["LNOBJ"] = "az"
	s, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	if strings.Index(s, "#BASE 62") > strings.Index(s, "#LNOBJ") {
		t.Fatal("base emitted after dependent header")
	}
}
func TestAuditNoBGMLaneShiftOnOverlap(t *testing.T) {
	d := New()
	d.Notes = []Note{{ID: "a", Channel: BGMLane, Kind: "normal", Value: 1}, {ID: "b", Channel: BGMLane, Kind: "normal", Value: 2}, {ID: "c", Channel: BGMLane + 1, Kind: "normal", Value: 3}}
	if _, e := Serialize(d); e == nil {
		t.Fatal("overlapping BGM silently shifted later lanes")
	}
	if d.Notes[2].Channel != BGMLane+1 {
		t.Fatal("live chart mutated")
	}
}
func TestAuditObjectLimitAllowsTrailingZeros(t *testing.T) {
	d, e := Parse("#00011:" + strings.Repeat("01", 200000) + "00")
	if e != nil || len(d.Notes) != 200000 {
		t.Fatal(len(d.Notes), e)
	}
}
func TestAuditOutputAllocationBound(t *testing.T) {
	d := New()
	for i := 0; i < 20; i++ {
		d.Notes = append(d.Notes, Note{ID: "n", Channel: 37, Kind: "normal", Value: 1, Position: 1.0 / 999983, Numerator: 1, Denominator: 999983})
	}
	if _, e := Serialize(d); e == nil {
		t.Fatal("oversized output accepted")
	}
}
func TestAuditTransportPreservesAllEncodings(t *testing.T) {
	for _, enc := range []string{"UTF-8", "Shift-JIS", "UTF-16LE", "UTF-16BE", "UTF-32LE", "UTF-32BE"} {
		d := New()
		d.Encoding = enc
		d.Headers["TITLE"] = "日本語"
		s, e := EncodeDocument(d)
		if e != nil {
			t.Fatal(e)
		}
		r, e := DecodeDocument(s, enc)
		if e != nil || r.Headers["TITLE"] != d.Headers["TITLE"] || r.Encoding != enc {
			t.Fatal(enc, r.Encoding, e)
		}
	}
	raw, _ := Encode("#TITLE 日本語\n#BPM 130", "UTF-32BE")
	r, e := DecodeDocument(base64.StdEncoding.EncodeToString(raw), "Auto")
	if e != nil || r.Encoding != "UTF-32BE" {
		t.Fatal(e)
	}
}
func TestAuditFractionalBpmDefinitionReuse(t *testing.T) {
	d, e := Parse("#BPMZZ 123.456789\n#00008:ZZ")
	if e != nil {
		t.Fatal(e)
	}
	s, e := Serialize(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := Parse(s)
	if e != nil || math.Abs(r.Notes[0].Value-123.456789) > 1e-10 {
		t.Fatal(r.Notes, e)
	}
}
