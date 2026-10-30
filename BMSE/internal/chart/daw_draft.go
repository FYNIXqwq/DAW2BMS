package chart

import (
	"bytes"
	"compress/zlib"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

type DawOrigin struct {
	TrackID        int    `json:"trackId"`
	TrackName      string `json:"trackName"`
	ChannelID      int    `json:"channelId"`
	InstrumentName string `json:"instrumentName"`
	KeyID          string `json:"keyId"`
	Pitch          int    `json:"pitch"`
	SourceIndex    int    `json:"sourceIndex"`
	OriginalTick   int64  `json:"originalTick"`
}

type DawDraft struct {
	Version       int    `json:"version"`
	SourceFile    string `json:"sourceFile"`
	SourceHash    string `json:"sourceHash"`
	DAW           string `json:"daw"`
	PPQ           int    `json:"ppq"`
	ArrangementID int    `json:"arrangementId"`
}

const draftPrefix = "*BMSE_DAW1 "
const draftLimit = 32 << 20

type draftRecord struct {
	At     string    `json:"at"`
	Origin DawOrigin `json:"origin"`
}
type savedDraft struct {
	Hash  string        `json:"hash"`
	Info  DawDraft      `json:"info"`
	Notes []draftRecord `json:"notes"`
}

func noteDraftKey(n Note) (string, error) {
	num, den, err := fraction(n)
	if err != nil {
		return "", err
	}
	kind := n.Kind
	if kind == "" {
		kind = "normal"
	}
	return fmt.Sprintf("%d/%d/%d/%d/%s/%g", n.Measure, num, den, n.Channel, kind, n.Value), nil
}
func draftHash(text string) string {
	text = strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n"))
	h := sha256.Sum256([]byte(text))
	return hex.EncodeToString(h[:])
}

// ASCII comments keep provenance in the same atomic save as the chart, including
// Shift-JIS charts. Players ignore them. No sibling JSON transaction is needed.
func appendDawDraft(d Document, text string) (string, error) {
	if d.DawDraft == nil {
		return text, nil
	}
	payload := savedDraft{Hash: draftHash(text), Info: *d.DawDraft}
	for _, n := range d.Notes {
		if n.DawOrigin == nil {
			continue
		}
		key, err := noteDraftKey(n)
		if err != nil {
			return "", err
		}
		payload.Notes = append(payload.Notes, draftRecord{key, *n.DawOrigin})
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	if len(data) > draftLimit {
		return "", fmt.Errorf("DAW provenance exceeds 32 MiB")
	}
	var compressed bytes.Buffer
	w := zlib.NewWriter(&compressed)
	if _, err = w.Write(data); err != nil {
		return "", err
	}
	if err = w.Close(); err != nil {
		return "", err
	}
	encoded := base64.StdEncoding.EncodeToString(compressed.Bytes())
	var result strings.Builder
	result.WriteString(text)
	for len(encoded) > 0 {
		size := 120
		if len(encoded) < size {
			size = len(encoded)
		}
		result.WriteString(draftPrefix + encoded[:size] + "\r\n")
		encoded = encoded[size:]
	}
	if result.Len() > 32<<20 {
		return "", fmt.Errorf("chart with DAW provenance exceeds 32 MiB")
	}
	return result.String(), nil
}

func splitDawDraft(text string) (string, string) {
	if !strings.Contains(text, draftPrefix) {
		return text, ""
	}
	lines := strings.Split(strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n"), "\n")
	var clean []string
	var encoded strings.Builder
	for _, line := range lines {
		if strings.HasPrefix(line, draftPrefix) {
			encoded.WriteString(strings.TrimPrefix(line, draftPrefix))
		} else {
			clean = append(clean, line)
		}
	}
	return strings.Join(clean, "\n"), encoded.String()
}

func restoreDawDraft(d *Document, text, encoded string) error {
	if encoded == "" {
		return nil
	}
	if d.SourceText != "" {
		return fmt.Errorf("conditional charts cannot restore DAW provenance")
	}
	compressed, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return err
	}
	r, err := zlib.NewReader(bytes.NewReader(compressed))
	if err != nil {
		return err
	}
	defer r.Close()
	data, err := io.ReadAll(io.LimitReader(r, draftLimit+1))
	if err != nil {
		return err
	}
	if len(data) > draftLimit {
		return fmt.Errorf("DAW provenance too large")
	}
	var saved savedDraft
	if err = json.Unmarshal(data, &saved); err != nil {
		return err
	}
	if saved.Info.Version != 1 || saved.Info.PPQ <= 0 || saved.Hash != draftHash(text) {
		return fmt.Errorf("DAW provenance no longer matches chart")
	}
	indices := map[string][]int{}
	for i, n := range d.Notes {
		key, err := noteDraftKey(n)
		if err != nil {
			return err
		}
		indices[key] = append(indices[key], i)
	}
	origins := map[int]DawOrigin{}
	for _, record := range saved.Notes {
		bucket := indices[record.At]
		if len(bucket) == 0 {
			return fmt.Errorf("DAW provenance event not found")
		}
		origins[bucket[0]] = record.Origin
		indices[record.At] = bucket[1:]
	}
	for i, origin := range origins {
		v := origin
		d.Notes[i].DawOrigin = &v
	}
	d.DawDraft = &saved.Info
	return nil
}
