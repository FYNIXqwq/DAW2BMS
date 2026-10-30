package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDawEngineDiscoveryAfterRelocation(t *testing.T) {
	root := filepath.Join(t.TempDir(), "移動した BMSE")
	write := func(relative string) string {
		path := filepath.Join(root, relative)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, nil, 0600); err != nil {
			t.Fatal(err)
		}
		return path
	}
	exe := write("BMSE/bin/BMSE3.exe")
	write("pyproject.toml")
	write("daw2bms/bridge.py")
	python := write(".venv/Scripts/python.exe")
	cfg := dawDefaultConfig(exe, t.TempDir(), "", "")
	if cfg.Mode != "python" || cfg.EngineRoot != root || cfg.Python != python {
		t.Fatalf("did not discover source checkout: %+v", cfg)
	}
	bundle := write("BMSE/bin/daw-engine/DAW2BMS.exe")
	cfg = dawDefaultConfig(exe, t.TempDir(), "", "")
	if cfg.Mode != "bundled" || !cfg.BundledAvailable || cfg.Python != "" || cfg.EngineRoot != "" {
		t.Fatalf("release should not depend on build-machine paths: %+v", cfg)
	}
	if got := dawBundleAt(exe, t.TempDir()); got != bundle {
		t.Fatal(got)
	}
	custom := dawDefaultConfig(exe, t.TempDir(), python, root)
	if custom.Mode != "python" || custom.Python != python {
		t.Fatal("explicit Python override ignored")
	}
}

func TestDawSavedExternalConfigSurvivesUpgrade(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "daw-import.json"), []byte(`{"python":"custom-python","engineRoot":"custom-root","language":"ja"}`), 0600); err != nil {
		t.Fatal(err)
	}
	s := &EditorService{configDir: dir}
	cfg, err := s.DawSettings()
	if err != nil || cfg.Mode != "python" || cfg.Python != "custom-python" || cfg.Language != "ja" {
		t.Fatalf("legacy manual settings lost: %+v %v", cfg, err)
	}
}

func TestDawBundleDoesNotUseArbitraryWorkingDirectory(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "bin", "daw-engine")
	if err := os.MkdirAll(path, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "DAW2BMS.exe"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	if got := dawBundleAt(filepath.Join(t.TempDir(), "BMSE3.exe"), dir); got != "" {
		t.Fatalf("loaded an unrelated cwd runtime: %s", got)
	}
}
