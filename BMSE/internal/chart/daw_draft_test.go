package chart

import (
	"strings"
	"testing"
)

func TestDawDraftRoundtripKeepsOccurrenceSources(t *testing.T) {
	d := New()
	d.WAV["1"] = "shared.wav"
	d.DawDraft = &DawDraft{Version: 1, SourceFile: "工程.flp", PPQ: 96}
	d.Notes = []Note{
		{ID: "a", Measure: 1, Position: 1.0 / 7, Numerator: 1, Denominator: 7, Channel: BGMLane + 4, Kind: "normal", Value: 1, DawOrigin: &DawOrigin{TrackID: 7, ChannelID: 2, TrackName: "主旋律", InstrumentName: "Piano", SourceIndex: 0}},
		{ID: "b", Measure: 1, Position: 1.0 / 7, Numerator: 1, Denominator: 7, Channel: 37, Kind: "normal", Value: 1, DawOrigin: &DawOrigin{TrackID: 8, ChannelID: 2, InstrumentName: "Piano", SourceIndex: 1}},
	}
	text, err := Serialize(d)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := Encode(text, "Shift-JIS")
	if err != nil {
		t.Fatal(err)
	}
	decoded, _, err := Decode(encoded, "Shift-JIS")
	if err != nil {
		t.Fatal(err)
	}
	got, err := Parse(decoded)
	if err != nil {
		t.Fatal(err)
	}
	if got.DawDraft == nil || got.DawDraft.SourceFile != "工程.flp" || len(got.Notes) != 2 {
		t.Fatalf("metadata lost: %+v", got)
	}
	for _, n := range got.Notes {
		if n.DawOrigin == nil || n.Position != 1.0/7 {
			t.Fatalf("source or timing lost: %+v", n)
		}
		want := 8
		if n.Channel == BGMLane+4 {
			want = 7
		}
		if n.DawOrigin.TrackID != want {
			t.Fatal("shared sample sources confused")
		}
	}
	if d.Notes[0].ID != "a" || d.Notes[0].DawOrigin.TrackName != "主旋律" {
		t.Fatal("serialize mutated input")
	}
	_, err = Serialize(got)
	if err != nil {
		t.Fatal(err)
	}
}

func TestDawDraftRejectsChangedChartWithoutDroppingMusic(t *testing.T) {
	d := New()
	d.WAV["1"] = "key.wav"
	d.DawDraft = &DawDraft{Version: 1, PPQ: 96}
	d.Notes = []Note{{ID: "a", Measure: 1, Denominator: 1, Channel: 37, Kind: "normal", Value: 1, DawOrigin: &DawOrigin{TrackID: 7}}}
	text, err := Serialize(d)
	if err != nil {
		t.Fatal(err)
	}
	for _, modified := range []string{strings.Replace(text, "#00111:", "#00211:", 1), strings.Replace(text, draftPrefix, draftPrefix+"!", 1)} {
		got, err := Parse(modified)
		if err != nil {
			t.Fatal(err)
		}
		if got.DawDraft != nil || got.Notes[0].DawOrigin != nil || len(got.Notes) != 1 || len(got.Warnings) == 0 {
			t.Fatal("stale mapping was silently reused")
		}
	}
}
