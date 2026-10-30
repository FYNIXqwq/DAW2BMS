//go:build !windows

package main

import (
	"os"
	"os/exec"
	"strings"
)

func hideDawProcess(cmd *exec.Cmd) {}

func dawSystemLanguage() string {
	lang := strings.ToLower(os.Getenv("LC_MESSAGES"))
	if lang == "" {
		lang = strings.ToLower(os.Getenv("LANG"))
	}
	if strings.HasPrefix(lang, "zh") {
		return "zh-TW"
	}
	if strings.HasPrefix(lang, "ja") {
		return "ja"
	}
	if strings.HasPrefix(lang, "ko") {
		return "ko"
	}
	return "en"
}
