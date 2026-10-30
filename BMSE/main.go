package main

import (
	"embed"
	"github.com/wailsapp/wails/v3/pkg/application"
	"github.com/wailsapp/wails/v3/pkg/events"
	"log"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	service := newEditor()
	app := application.New(application.Options{
		Name: "BMSE", Description: "BMx Sequence Editor — Wails 3",
		Services: []application.Service{application.NewService(service)},
		Assets:   application.AssetOptions{Handler: application.AssetFileServerFS(assets)},
		Mac:      application.MacOptions{ApplicationShouldTerminateAfterLastWindowClosed: true},
	})
	service.app = app
	window := app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title: "BMx Sequence Editor 3 — Untitled", Width: 1280, Height: 900,
		MinWidth: 900, MinHeight: 650, URL: "/", BackgroundColour: application.NewRGB(240, 240, 240),
		EnableFileDrop: true,
	})
	service.window = window
	window.OnWindowEvent(events.Common.WindowFilesDropped, func(event *application.WindowEvent) {
		app.Event.Emit("files-dropped", map[string]any{"files": event.Context().DroppedFiles()})
	})
	window.RegisterHook(events.Common.WindowClosing, func(e *application.WindowEvent) {
		if service.diskOperations.Load() > 0 {
			e.Cancel()
			app.Event.Emit("operation-pending")
			return
		}
		if service.dirty.Load() {
			e.Cancel()
			app.Event.Emit("request-close")
		}
	})
	if err := app.Run(); err != nil {
		log.Fatal(err)
	}
}
