package chart

import (
	"encoding/base64"
	"fmt"
)

func DecodeDocument(data, encoding string) (Document, error) {
	if len(data) > 45<<20 {
		return New(), fmt.Errorf("file too large")
	}
	bytes, e := base64.StdEncoding.DecodeString(data)
	if e != nil {
		return New(), e
	}
	if len(bytes) > 32<<20 {
		return New(), fmt.Errorf("file too large")
	}
	text, name, e := Decode(bytes, encoding)
	if e != nil {
		return New(), e
	}
	d, e := Parse(text)
	d.Encoding = name
	return d, e
}
func EncodeDocument(d Document) (string, error) {
	text, e := Serialize(d)
	if e != nil {
		return "", e
	}
	bytes, e := Encode(text, d.Encoding)
	if e != nil {
		return "", e
	}
	if len(bytes) > 32<<20 {
		return "", fmt.Errorf("encoded file exceeds 32 MiB")
	}
	return base64.StdEncoding.EncodeToString(bytes), nil
}
