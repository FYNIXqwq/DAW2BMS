//go:build !windows

package storage

import "os"

func replace(src, dst string) error { return os.Rename(src, dst) }
