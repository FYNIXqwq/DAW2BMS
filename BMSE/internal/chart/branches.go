package chart

import (
	"fmt"
	"strconv"
	"strings"
)

type BranchChoice struct {
	Line    int    `json:"line"`
	Maximum int    `json:"maximum"`
	Fixed   int    `json:"fixed"`
	Kind    string `json:"kind"`
}

func Branches(text string) []BranchChoice {
	r := []BranchChoice{}
	for i, l := range strings.Split(strings.ReplaceAll(text, "\r", ""), "\n") {
		p := strings.Fields(l)
		if len(p) < 2 {
			continue
		}
		c := strings.ToUpper(p[0])
		if c == "#RANDOM" || c == "#RONDAM" || c == "#SETRANDOM" || c == "#SWITCH" || c == "#SETSWITCH" {
			n, _ := strconv.Atoi(p[1])
			choice := BranchChoice{Line: i + 1, Maximum: n, Kind: c}
			if c == "#SETRANDOM" || c == "#SETSWITCH" {
				choice.Fixed = n
			}
			r = append(r, choice)
		}
	}
	return r
}

// ResolveBranches creates a separate flattened document; the original conditional text is never rewritten.
func ResolveBranches(text string, choices map[int]int) (Document, error) {
	type frame struct {
		parent, active, matched bool
		value                   int
	}
	type random struct {
		value    int
		active   bool
		isSwitch bool
		parent   bool
		matched  bool
	}
	stack := []frame{}
	randoms := []random{}
	active := true
	out := []string{}
	for i, line := range strings.Split(strings.ReplaceAll(text, "\r", ""), "\n") {
		p := strings.Fields(line)
		if len(p) == 0 {
			if active {
				out = append(out, line)
			}
			continue
		}
		cmd := strings.ToUpper(p[0])
		value := 0
		if len(p) > 1 {
			value, _ = strconv.Atoi(p[1])
		}
		switch cmd {
		case "#RANDOM", "#RONDAM", "#SETRANDOM", "#SWITCH", "#SETSWITCH":
			if value <= 0 {
				return New(), fmt.Errorf("line %d: invalid branch range", i+1)
			}
			v := choices[i+1]
			if cmd == "#SETRANDOM" || cmd == "#SETSWITCH" {
				v = value
			} else if v == 0 {
				v = 1
			}
			if v < 1 || v > value {
				return New(), fmt.Errorf("line %d: choice must be 1..%d", i+1, value)
			}
			isSwitch := cmd == "#SWITCH" || cmd == "#SETSWITCH"
			randoms = append(randoms, random{value: v, active: active, isSwitch: isSwitch, parent: active})
			if isSwitch {
				active = false
			}
		case "#IF":
			if len(randoms) == 0 {
				return New(), fmt.Errorf("line %d: IF has no RANDOM", i+1)
			}
			ok := randoms[len(randoms)-1].value == value
			stack = append(stack, frame{active, active && ok, ok, randoms[len(randoms)-1].value})
			active = active && ok
		case "#ELSEIF", "#ELSE":
			if len(stack) == 0 {
				return New(), fmt.Errorf("line %d: unmatched %s", i+1, cmd)
			}
			f := &stack[len(stack)-1]
			ok := cmd == "#ELSE" || f.value == value
			f.active = f.parent && !f.matched && ok
			f.matched = f.matched || ok
			active = f.active
		case "#ENDIF", "#IFEND", "#END":
			if len(stack) == 0 {
				return New(), fmt.Errorf("line %d: unmatched ENDIF", i+1)
			}
			active = stack[len(stack)-1].parent
			stack = stack[:len(stack)-1]
		case "#ENDRANDOM":
			if len(randoms) > 0 {
				active = randoms[len(randoms)-1].active
				randoms = randoms[:len(randoms)-1]
			}
		case "#CASE", "#DEF":
			if len(randoms) == 0 || !randoms[len(randoms)-1].isSwitch {
				return New(), fmt.Errorf("line %d: CASE without SWITCH", i+1)
			}
			f := &randoms[len(randoms)-1]
			ok := cmd == "#DEF" || f.value == value
			active = f.parent && (active || !f.matched && ok)
			f.matched = f.matched || ok
		case "#SKIP":
			active = false
		case "#ENDSW", "#ENDSWITCH":
			if len(randoms) == 0 || !randoms[len(randoms)-1].isSwitch {
				return New(), fmt.Errorf("line %d: ENDSW without SWITCH", i+1)
			}
			active = randoms[len(randoms)-1].parent
			randoms = randoms[:len(randoms)-1]
		default:
			if active {
				out = append(out, line)
			}
		}
	}
	if len(stack) > 0 {
		return New(), fmt.Errorf("unterminated IF")
	}
	d, e := Parse(strings.Join(out, "\n"))
	if e == nil {
		d.Warnings = append(d.Warnings, "已按指定分支生成独立谱面；原始随机定义未被覆盖。")
	}
	return d, e
}
