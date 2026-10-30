import { test, expect } from "@playwright/test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import path from "node:path";

const python = process.env.DAW2BMS_TEST_PYTHON || "python.exe";
function fixture(wait = false) {
  const root = mkdtempSync(path.resolve("../bin/daw-e2e-"));
  const engine = path.join(root, "engine");
  mkdirSync(path.join(engine, "daw2bms"), { recursive: true });
  writeFileSync(path.join(engine, "daw2bms", "__init__.py"), "");
  writeFileSync(
    path.join(engine, "daw2bms", "bridge.py"),
    `
import json,sys,pathlib,hashlib,wave
r=json.loads(sys.stdin.readline());p=pathlib.Path(r['source'])
def emit(e):print(json.dumps(e),flush=True)
emit({'type':'hello','protocol':1,'version':'test'})
if r['action']=='inspect':
 emit({'type':'tracks','data':{'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'daw':'fl_studio','arrangements':[{'id':0,'name':'Fixture Arrangement','tracks':[{'id':7,'name':'Lead','notes':1,'supported':True},{'id':8,'name':'Accompaniment','notes':1,'supported':True},{'id':9,'name':'Muted layer','notes':1,'supported':True}]}]}})
else:
 out=pathlib.Path(r['out']);out.mkdir(parents=True)
 emit({'type':'progress','stage':2,'message':'Fixture render in progress','level':'info'})
 if p.read_text()=='wait':
  command=json.loads(sys.stdin.readline())
  emit({'type':'cancelled','data':{'status':'cancelled','output_directory':str(out),'chart':None,'midi':None},'message':'Cancelled; files retained'})
 else:
  audio=out/'chart'/'audio';audio.mkdir(parents=True)
  with wave.open(str(audio/'key.wav'),'wb') as w:w.setparams((1,2,8000,80,'NONE',''));w.writeframes(b'\\x00\\x10'*80)
  lines=['#TITLE Imported DAW fixture','#BPM 120','#WAV01 audio/key.wav'];play=bgm=0
  for i in (7,8,9):
   if i in r['options']['exclude_tracks']:continue
   ch='11' if i in r['options']['play_tracks'] else '01';play+=ch=='11';bgm+=ch=='01';lines.append('#%03d%s:01'%(i-6,ch))
  (out/'chart'/'test.bme').write_text('\\n'.join(lines))
  (out/'received.json').write_text(json.dumps(r))
  emit({'type':'result','data':{'status':'complete','output_directory':str(out),'chart':'chart/test.bme','audio_complete':True,'playable_notes':play,'bgm_events':bgm,'midi_only_notes':0}})
`,
  );
  const source = path.join(root, "工程 with spaces.flp");
  writeFileSync(source, wait ? "wait" : "fixture");
  return { root, engine, source };
}
async function configure(
  page: import("@playwright/test").Page,
  engine: string,
) {
  await page.goto("http://127.0.0.1:9247/");
  await page.evaluate(
    async ({ python, engine }) => {
      const url = "/wails/runtime.js";
      const { Call } = await import(url);
      await Call.ByName("main.EditorService.DawSaveSettings", {
        python,
        engineRoot: engine,
        language: "en",
      });
    },
    { python, engine },
  );
}
async function showImport(
  page: import("@playwright/test").Page,
  source: string,
  row = "7 · Lead",
) {
  await page.getByRole("button", { name: "文件(F)", exact: true }).click();
  await page
    .getByRole("menuitem", { name: "导入 DAW 工程…", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "导入 DAW 工程",
    exact: true,
  });
  await dialog
    .getByLabel("FLP / ALS project file", { exact: true })
    .fill(source);
  await dialog
    .getByRole("button", { name: "Read tracks", exact: true })
    .click();
  await expect(
    dialog.getByRole("cell", { name: row, exact: true }),
  ).toBeVisible();
  return dialog;
}
test("DAW conversion preserves track roles, unsaved work and relative keysounds", async ({
  page,
}) => {
  const f = fixture();
  await configure(page, f.engine);
  await page.getByLabel("标题", { exact: true }).fill("Keep my unsaved chart");
  await page.getByLabel("标题", { exact: true }).blur();
  const dialog = await showImport(page, f.source);
  await dialog.getByLabel("Role for track 7").selectOption("play");
  await dialog.getByLabel("Role for track 9").selectOption("exclude");
  await dialog
    .getByRole("button", { name: "Start conversion", exact: true })
    .click();
  await expect(
    dialog.getByRole("button", { name: "Open generated chart", exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "Open generated chart", exact: true })
    .click();
  const confirm = page.getByRole("dialog", { name: "保存修改", exact: true });
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: "取消", exact: true }).click();
  await expect(dialog).toBeVisible();
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Keep my unsaved chart",
  );
  await dialog
    .getByRole("button", { name: "Open generated chart", exact: true })
    .click();
  await confirm.getByRole("button", { name: "不保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByLabel("标题", { exact: true })).toHaveValue(
    "Imported DAW fixture",
  );
  await expect(page.locator(".statusbar")).toContainText("2 OBJ");
  const data = await page.evaluate(async () => {
    const url = "/wails/runtime.js";
    const { Call } = await import(url);
    const job = await Call.ByName("main.EditorService.DawStatus");
    const chart = await Call.ByName("main.EditorService.DawOpenResult", job.id);
    const audio = await Call.ByName(
      "main.EditorService.MaterialData",
      chart.path,
      "audio/key.wav",
    );
    return { job, chart, audio };
  });
  expect(data.audio).toContain("base64,");
  expect(data.chart.path).toContain("chart");
  const received = JSON.parse(
    readFileSync(path.join(data.job.outputDir, "received.json"), "utf8"),
  );
  expect(received.options.play_tracks).toEqual([7]);
  expect(received.options.exclude_tracks).toEqual([9]);
  expect(readFileSync(f.source, "utf8")).toBe("fixture");
});
test("DAW cancellation blocks closing and does not replace the editor document", async ({
  page,
}) => {
  const f = fixture(true);
  await configure(page, f.engine);
  const dialog = await showImport(page, f.source);
  await dialog
    .getByRole("button", { name: "Start conversion", exact: true })
    .click();
  await expect(dialog.getByLabel("Log", { exact: true })).toHaveValue(
    /Fixture render in progress/,
  );
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("关闭对话框").click();
  await expect(dialog).toBeVisible();
  await dialog
    .getByRole("button", { name: "Stop after this step", exact: true })
    .click();
  await expect(dialog.getByRole("status")).toContainText("Conversion stopped");
  await expect(
    dialog.getByRole("button", { name: "Open generated chart", exact: true }),
  ).toHaveCount(0);
  await dialog.getByLabel("关闭对话框").click();
  await expect(dialog).toHaveCount(0);
});
test("real DAW2BMS bridge reads ALS and preserves MIDI without starting a DAW", async ({
  page,
}) => {
  test.skip(
    !process.env.DAW2BMS_TEST_ENGINE,
    "Set DAW2BMS_TEST_ENGINE for actual Python bridge integration",
  );
  const root = mkdtempSync(path.resolve("../bin/daw-real-"));
  const source = path.join(root, "generated.als");
  writeFileSync(
    source,
    '<Ableton Creator="Ableton Live 12" MinorVersion="12.0_test"><LiveSet><Tracks><MidiTrack Id="7"><Name><EffectiveName Value="MIDI fixture"/></Name><DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events><MidiClip Id="0" Time="0"><CurrentStart Value="0"/><CurrentEnd Value="4"/><Loop><LoopStart Value="0"/><LoopEnd Value="4"/><StartRelative Value="0"/><LoopOn Value="false"/></Loop><Notes><KeyTracks><KeyTrack><MidiKey Value="60"/><Notes><MidiNoteEvent Time="0" Duration="1" Velocity="100"/></Notes></KeyTrack></KeyTracks></Notes></MidiClip></Events></ArrangerAutomation></ClipTimeable></MainSequencer></DeviceChain></MidiTrack></Tracks></LiveSet></Ableton>',
  );
  await configure(page, process.env.DAW2BMS_TEST_ENGINE!);
  const dialog = await showImport(page, source, "7 · MIDI fixture");
  await expect(
    dialog.getByRole("cell", { name: "7 · MIDI fixture", exact: true }),
  ).toBeVisible();
  await dialog.getByLabel("Role for track 7").selectOption("play");
  await dialog
    .getByRole("button", { name: "Start conversion", exact: true })
    .click();
  await expect(dialog.getByRole("status")).toContainText("MIDI preserved");
  const job = await page.evaluate(async () => {
    const url = "/wails/runtime.js";
    const { Call } = await import(url);
    return Call.ByName("main.EditorService.DawStatus");
  });
  expect(
    readFileSync(path.join(job.outputDir, "song.mid"))
      .subarray(0, 4)
      .toString(),
  ).toBe("MThd");
  await expect(
    dialog.getByRole("button", { name: "Open generated chart", exact: true }),
  ).toHaveCount(0);
});

test('DAW language switching preserves source and roles and remembers the choice',async({page})=>{
  const f=fixture();await configure(page,f.engine);const dialog=await showImport(page,f.source);
  await dialog.getByLabel('Role for track 7').selectOption('play');
  for(const [language,label] of [['zh-TW','讀取音軌'],['ja','トラックを読む'],['ko','트랙 읽기'],['en','Read tracks']]){
    await dialog.locator('.daw-intro select').selectOption(language);
    await expect(dialog.getByRole('button',{name:label,exact:true})).toBeVisible();
    await expect(dialog.locator('tbody select').first()).toHaveValue('play');
    await expect(dialog.locator('.daw-path input').first()).toHaveValue(f.source);
  }
  await dialog.locator('.daw-intro select').selectOption('ko');
  await dialog.getByLabel('关闭对话框').click();
  await page.getByRole('button',{name:'文件(F)',exact:true}).click();await page.getByRole('menuitem',{name:'导入 DAW 工程…',exact:true}).click();
  await expect(dialog.locator('.daw-intro select')).toHaveValue('ko');
  await expect(dialog.getByRole('button',{name:'트랙 읽기',exact:true})).toBeVisible();
});
