package main

import "bmse/internal/chart"

func (s *EditorService) Branches(text string) []chart.BranchChoice { return chart.Branches(text) }
func (s *EditorService) ResolveBranches(text string, choices map[int]int) (chart.Document, error) {
	return chart.ResolveBranches(text, choices)
}
