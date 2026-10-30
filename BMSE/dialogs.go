package main

import "github.com/wailsapp/wails/v3/pkg/application"

// Native dialogs are adapted behind this interface so cancellation and save flows
// can be verified without desktop automation.
type fileDialogs interface {
	OpenChart() (string, error)
	SaveChart(string) (string, error)
	PickViewer() (string, error)
	PickMaterials(string) ([]string, error)
}
type wailsDialogs struct{ app *application.App }

func (d wailsDialogs) OpenChart() (string, error) {
	return d.app.Dialog.OpenFile().SetTitle("打开 BMS / iBMSC 谱面").AddFilter("谱面", "*.bms;*.bme;*.bml;*.pms;*.ibmsc").PromptForSingleSelection()
}
func (d wailsDialogs) SaveChart(name string) (string, error) {
	return d.app.Dialog.SaveFile().SetFilename(name).AddFilter("BMS 谱面", "*.bms;*.bme;*.bml;*.pms").PromptForSingleSelection()
}
func (d wailsDialogs) PickViewer() (string, error) {
	return d.app.Dialog.OpenFile().SetTitle("选择外部播放器").AddFilter("可执行文件", "*.exe").PromptForSingleSelection()
}
func (d wailsDialogs) PickMaterials(kind string) ([]string, error) {
	dialog := d.app.Dialog.OpenFile().SetTitle("选择 " + kind + " 素材")
	if kind == "WAV" {
		dialog.AddFilter("音频", "*.wav;*.ogg;*.mp3;*.flac")
	} else {
		dialog.AddFilter("图像 / 视频", "*.bmp;*.png;*.jpg;*.jpeg;*.gif;*.webp;*.mp4;*.avi")
	}
	return dialog.PromptForMultipleSelection()
}
func (s *EditorService) fileDialogs() fileDialogs {
	if s.dialogs != nil {
		return s.dialogs
	}
	return wailsDialogs{s.app}
}
