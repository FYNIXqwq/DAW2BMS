//go:build windows

package chart

import (
	"fmt"
	"golang.org/x/sys/windows"
)

func systemEncoding() string {
	cp := windows.GetACP()
	switch cp {
	case 65001:
		return "UTF-8"
	case 932:
		return "Shift-JIS"
	case 936:
		return "GBK"
	case 949:
		return "EUC-KR"
	case 950:
		return "Big5"
	case 874:
		return "windows-874"
	}
	return fmt.Sprintf("windows-%d", cp)
}
