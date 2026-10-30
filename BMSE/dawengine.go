package main

import (
	"os"
	"os/exec"
	"path/filepath"
)

func dawFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

// Releases locate their runtime relative to the EXE, never a saved build-machine path.
func dawBundleAt(executable, cwd string) string {
	name := "DAW2BMS.exe"
	if path := filepath.Join(filepath.Dir(executable), "daw-engine", name); dawFile(path) {
		return path
	}
	// `go run` uses a temporary EXE; only use a local build in this source layout.
	if dawFile(filepath.Join(cwd, "dawservice.go")) && dawFile(filepath.Join(cwd, "..", "daw2bms", "bridge.py")) {
		if path := filepath.Join(cwd, "bin", "daw-engine", name); dawFile(path) {
			return path
		}
	}
	return ""
}

func dawBundlePath() string {
	exe, _ := os.Executable()
	cwd, _ := os.Getwd()
	return dawBundleAt(exe, cwd)
}

func dawSourceRoot(executable, cwd string) string {
	for _, start := range []string{filepath.Dir(executable), cwd} {
		for i, dir := 0, start; i < 3 && dir != ""; i, dir = i+1, filepath.Dir(dir) {
			if dawFile(filepath.Join(dir, "pyproject.toml")) && dawFile(filepath.Join(dir, "daw2bms", "bridge.py")) {
				return dir
			}
		}
	}
	return ""
}

func dawDefaultConfig(executable, cwd, python, root string) DawConfig {
	cfg := DawConfig{Mode: "python", Python: python, EngineRoot: root, Language: "system"}
	cfg.BundledAvailable = dawBundleAt(executable, cwd) != ""
	if python == "" && root == "" && cfg.BundledAvailable {
		cfg.Mode = "bundled"
		return cfg
	}
	if cfg.EngineRoot == "" && python == "" {
		cfg.EngineRoot = dawSourceRoot(executable, cwd)
	}
	if cfg.Python == "" && cfg.EngineRoot != "" {
		for _, relative := range []string{".venv/Scripts/python.exe", ".venv/bin/python"} {
			if path := filepath.Join(cfg.EngineRoot, relative); dawFile(path) {
				cfg.Python = path
				break
			}
		}
	}
	if cfg.Python == "" {
		cfg.Python, _ = exec.LookPath("python")
	}
	return cfg
}
