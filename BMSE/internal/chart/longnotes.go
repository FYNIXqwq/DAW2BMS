package chart

import (
	"fmt"
	"math"
	"sort"
)

type lnSegment struct {
	start, end float64
	channel    int
	value      float64
}

func normalizeLN2(d *Document, segments []lnSegment) error {
	sort.Slice(segments, func(i, j int) bool {
		if segments[i].channel != segments[j].channel {
			return segments[i].channel < segments[j].channel
		}
		return segments[i].start < segments[j].start
	})
	add := func(t float64, ch int, value float64) error {
		if len(d.Notes) >= 200000 {
			return fmt.Errorf("normalized chart exceeds 200000 objects")
		}
		m := int(math.Floor(t))
		if m > 999 {
			return fmt.Errorf("LNTYPE 2 endpoint exceeds measure 999")
		}
		d.Notes = append(d.Notes, Note{ID: fmt.Sprintf("ln2-%d", len(d.Notes)+1), Measure: m, Position: t - float64(m), Channel: ch, Kind: "long", Value: value})
		return nil
	}
	for i := 0; i < len(segments); {
		s := segments[i]
		i++
		for i < len(segments) && segments[i].channel == s.channel && math.Abs(segments[i].start-s.end) < 1e-10 {
			s.end = segments[i].end
			i++
		}
		if e := add(s.start, s.channel, s.value); e != nil {
			return e
		}
		if e := add(s.end, s.channel, s.value); e != nil {
			return e
		}
	}
	d.Headers["LNTYPE"] = "1"
	d.Warnings = append(d.Warnings, "LNTYPE 2 已按连续占用区间转换为 LNTYPE 1 端点，保持音符起止时间。")
	return nil
}

func validateLongNotes(d Document) []Issue {
	result := []Issue{}
	tracks := map[int][]Note{}
	marker, _ := DecodeID(d.Headers["LNOBJ"], d.Base)
	for _, n := range d.Notes {
		if KeyChannel(n.Channel) && n.Kind != "invisible" {
			tracks[n.Channel] = append(tracks[n.Channel], n)
		}
	}
	for _, notes := range tracks {
		sort.SliceStable(notes, func(i, j int) bool {
			return float64(notes[i].Measure)+notes[i].Position < float64(notes[j].Measure)+notes[j].Position
		})
		var head *Note
		var previous *Note
		add := func(n Note, m string) { result = append(result, Issue{"error", m, n.ID, n.Measure}) }
		for i := range notes {
			n := notes[i]
			if n.Kind == "long" {
				if head == nil {
					h := n
					head = &h
				} else {
					if n.Measure == head.Measure && n.Position == head.Position {
						add(n, "长音符长度为零")
					}
					head = nil
				}
				previous = nil
				continue
			}
			if head != nil && float64(n.Measure)+n.Position > float64(head.Measure)+head.Position {
				add(n, "长音符区间内存在其他可见对象")
			}
			if n.Kind == "normal" && marker > 0 && int(n.Value) == marker {
				if previous == nil || previous.Kind != "normal" || int(previous.Value) == marker || previous.Measure == n.Measure && previous.Position == n.Position {
					add(n, "LNOBJ 缺少有效起点")
				}
				previous = nil
			} else if n.Kind == "normal" {
				p := n
				previous = &p
			}
		}
	}
	sort.SliceStable(result, func(i, j int) bool { return result[i].Measure < result[j].Measure })
	return result
}
