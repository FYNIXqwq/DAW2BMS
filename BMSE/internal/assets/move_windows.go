//go:build windows

package assets

import "golang.org/x/sys/windows"

// No REPLACE_EXISTING flag: a target created after preview must never be overwritten.
func moveNoReplace(from, to string) error {
	src, e := windows.UTF16PtrFromString(from)
	if e != nil {
		return e
	}
	dst, e := windows.UTF16PtrFromString(to)
	if e != nil {
		return e
	}
	return windows.MoveFileEx(src, dst, windows.MOVEFILE_WRITE_THROUGH)
}
