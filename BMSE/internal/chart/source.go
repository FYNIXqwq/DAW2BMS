package chart

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"strings"
)

var controlLine = regexp.MustCompile(`(?im)^\s*#(?:RANDOM|RONDAM|SETRANDOM|SWITCH|SETSWITCH|IF|ELSEIF|ELSE|ENDIF|IFEND|ENDRANDOM|ENDSW|ENDSWITCH|CASE|DEF|SKIP)(?:\s|$)`)

func HasControlFlow(text string) bool { return controlLine.MatchString(text) }
func sourceHash(d Document) string {
	d.Path = ""
	d.EditorMode = ""
	d.Encoding = ""
	d.Warnings = nil
	d.SourceHash = ""
	d.Notes = append([]Note(nil), d.Notes...)
	for i := range d.Notes {
		d.Notes[i].ID = ""
	}
	b, e := json.Marshal(d)
	if e != nil {
		return "invalid"
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func RememberSource(d *Document, text string) {
	if HasControlFlow(text) {
		d.SourceText = text
		d.SourceHash = sourceHash(*d)
	}
}
func sourceMatches(d Document) bool { return d.SourceHash != "" && d.SourceHash == sourceHash(d) }
func opaqueExtra(d Document) bool   { return HasControlFlow(strings.Join(d.Extra, "\n")) }
