package chart

import (
	"bytes"
	"fmt"
	"golang.org/x/text/encoding"
	"golang.org/x/text/encoding/ianaindex"
	"golang.org/x/text/encoding/japanese"
	"golang.org/x/text/encoding/korean"
	"golang.org/x/text/encoding/simplifiedchinese"
	"golang.org/x/text/encoding/traditionalchinese"
	"golang.org/x/text/encoding/unicode"
	"golang.org/x/text/encoding/unicode/utf32"
	"strings"
	"unicode/utf8"
)

func codec(name string) encoding.Encoding {
	switch strings.ToUpper(name) {
	case "SHIFT-JIS", "SHIFT_JIS", "SJIS":
		return japanese.ShiftJIS
	case "EUC-KR":
		return korean.EUCKR
	case "GBK", "CP936":
		return simplifiedchinese.GBK
	case "BIG5", "CP950":
		return traditionalchinese.Big5
	case "UTF-16LE":
		return unicode.UTF16(unicode.LittleEndian, unicode.UseBOM)
	case "UTF-16BE":
		return unicode.UTF16(unicode.BigEndian, unicode.UseBOM)
	case "UTF-32LE":
		return utf32.UTF32(utf32.LittleEndian, utf32.UseBOM)
	case "UTF-32BE":
		return utf32.UTF32(utf32.BigEndian, utf32.UseBOM)
	}
	c, _ := ianaindex.MIME.Encoding(name)
	return c
}
func Decode(data []byte, requested string) (string, string, error) {
	name := requested
	if strings.EqualFold(name, "System") || strings.EqualFold(name, "SYS") {
		name = systemEncoding()
	}
	if name == "" || name == "Auto" {
		switch {
		case bytes.HasPrefix(data, []byte{255, 254, 0, 0}):
			name = "UTF-32LE"
		case bytes.HasPrefix(data, []byte{0, 0, 254, 255}):
			name = "UTF-32BE"
		case bytes.HasPrefix(data, []byte{255, 254}):
			name = "UTF-16LE"
		case bytes.HasPrefix(data, []byte{254, 255}):
			name = "UTF-16BE"
		case utf8.Valid(data):
			name = "UTF-8"
		default:
			name = "Shift-JIS"
		}
	}
	if strings.EqualFold(name, "UTF-8") || strings.EqualFold(name, "UTF-8 BOM") {
		if !utf8.Valid(data) {
			return "", name, fmt.Errorf("invalid UTF-8; choose another encoding")
		}
		if bytes.HasPrefix(data, []byte{239, 187, 191}) {
			name = "UTF-8 BOM"
		}
		return strings.TrimPrefix(string(data), "\ufeff"), name, nil
	}
	c := codec(name)
	if c == nil {
		return "", name, fmt.Errorf("unsupported encoding %q", name)
	}
	decoded, e := c.NewDecoder().Bytes(data)
	if e != nil {
		return "", name, e
	}
	if bytes.Contains(decoded, []byte("\ufffd")) {
		return "", name, fmt.Errorf("decoding produced replacement characters; choose another encoding")
	}
	return string(decoded), name, nil
}
func Encode(text, name string) ([]byte, error) {
	if strings.EqualFold(name, "System") || strings.EqualFold(name, "SYS") {
		name = systemEncoding()
	}
	if strings.EqualFold(name, "UTF-8 BOM") {
		return append([]byte{239, 187, 191}, []byte(strings.TrimPrefix(text, "\ufeff"))...), nil
	}
	if name == "" || strings.EqualFold(name, "UTF-8") {
		return []byte(text), nil
	}
	c := codec(name)
	if c == nil {
		return nil, fmt.Errorf("unsupported encoding %q", name)
	}
	return c.NewEncoder().Bytes([]byte(text))
}
