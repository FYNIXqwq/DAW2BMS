//go:build windows

package main

import (
	"os/exec"
	"syscall"
)

func hideDawProcess(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
}

func dawSystemLanguage() string {
	id, _, _ := syscall.NewLazyDLL("kernel32.dll").NewProc("GetUserDefaultUILanguage").Call()
	switch id & 0x3ff {
	case 4:
		return "zh-TW"
	case 17:
		return "ja"
	case 18:
		return "ko"
	default:
		return "en"
	}
}
