//go:build !windows

package assets

import "os"

func moveNoReplace(from, to string) error {
	if e := os.Link(from, to); e != nil {
		return e
	}
	if e := os.Remove(from); e != nil {
		_ = os.Remove(to)
		return e
	}
	return nil
}
