package main

import (
	assetops "bmse/internal/assets"
	"bmse/internal/chart"
	"fmt"
	"sync"
)

var assetPlans = struct {
	sync.Mutex
	plans map[string]assetops.Plan
}{plans: map[string]assetops.Plan{}}

func (s *EditorService) PlanAssets(d chart.Document, mode string) (assetops.Plan, error) {
	p, e := assetops.Prepare(d, mode)
	if e != nil {
		return p, e
	}
	assetPlans.Lock()
	defer assetPlans.Unlock()
	if len(assetPlans.plans) > 20 {
		assetPlans.plans = map[string]assetops.Plan{}
	}
	assetPlans.plans[p.Token] = p
	return p, nil
}
func (s *EditorService) ApplyAssets(token string) (assetops.Result, error) {
	s.diskOperations.Add(1)
	defer s.diskOperations.Add(-1)
	assetPlans.Lock()
	defer assetPlans.Unlock()
	p, ok := assetPlans.plans[token]
	if !ok {
		return assetops.Result{}, fmt.Errorf("操作预览已过期")
	}
	delete(assetPlans.plans, token)
	return assetops.Execute(p)
}

func (s *EditorService) PlanRename(d chart.Document, from, to string) (assetops.Plan, error) {
	p, e := assetops.PrepareRename(d, from, to)
	if e != nil {
		return p, e
	}
	assetPlans.Lock()
	defer assetPlans.Unlock()
	if len(assetPlans.plans) > 20 {
		assetPlans.plans = map[string]assetops.Plan{}
	}
	assetPlans.plans[p.Token] = p
	return p, nil
}
func (s *EditorService) RestoreAssets(path string) (chart.Document, error) {
	s.diskOperations.Add(1)
	defer s.diskOperations.Add(-1)
	return assetops.Restore(path)
}
func (s *EditorService) RestoreAssetsForChart(path, chartPath string) (chart.Document, error) {
	s.diskOperations.Add(1)
	defer s.diskOperations.Add(-1)
	return assetops.Restore(path, chartPath)
}
