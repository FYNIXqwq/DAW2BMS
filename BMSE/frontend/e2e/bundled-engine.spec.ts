import { test, expect } from '@playwright/test';
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

test('bundled runtime converts ALS without Python configuration and survives language changes', async ({page}) => {
  await page.goto('http://127.0.0.1:9247/');
  const available = await page.evaluate(async () => {
    const url = '/wails/runtime.js';
    const { Call } = await import(url);
    const config = await Call.ByName('main.EditorService.DawSettings');
    if (config.bundledAvailable) {
      await Call.ByName('main.EditorService.DawSaveSettings', {mode:'bundled',language:'en'});
    }
    return config.bundledAvailable;
  });
  test.skip(!available, 'Build the bundled runtime first with build-engine.ps1');
  const root = mkdtempSync(path.resolve('../bin/bundled-e2e-'));
  const source = path.join(root, '内置引擎 test.als');
  const xml = '<Ableton Creator="Ableton Live 12" MinorVersion="12.0_test"><LiveSet><Tracks><MidiTrack Id="7"><Name><EffectiveName Value="MIDI fixture"/></Name><DeviceChain><MainSequencer><ClipTimeable><ArrangerAutomation><Events><MidiClip Id="0" Time="0"><CurrentStart Value="0"/><CurrentEnd Value="4"/><Loop><LoopStart Value="0"/><LoopEnd Value="4"/><StartRelative Value="0"/><LoopOn Value="false"/></Loop><Notes><KeyTracks><KeyTrack><MidiKey Value="60"/><Notes><MidiNoteEvent Time="0" Duration="1" Velocity="100"/></Notes></KeyTrack></KeyTracks></Notes></MidiClip></Events></ArrangerAutomation></ClipTimeable></MainSequencer></DeviceChain></MidiTrack></Tracks></LiveSet></Ableton>';
  writeFileSync(source, xml);
  await page.getByRole('button',{name:'文件(F)',exact:true}).click();
  await page.getByRole('menuitem',{name:'导入 DAW 工程…',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'导入 DAW 工程',exact:true});
  await dialog.getByText('Conversion engine',{exact:true}).click();
  await expect(dialog.getByLabel('Engine mode',{exact:true})).toHaveValue('bundled');
  await expect(dialog.getByText('Ready to convert. No Python setup required.')).toBeVisible();
  await expect(dialog.getByLabel('Python executable',{exact:true})).toHaveCount(0);
  await dialog.getByLabel('Engine mode',{exact:true}).selectOption('python');
  await expect(dialog.getByLabel('Python executable',{exact:true})).toBeVisible();
  await dialog.getByLabel('Engine mode',{exact:true}).selectOption('bundled');
  await dialog.getByLabel('FLP / ALS project file',{exact:true}).fill(source);
  await dialog.getByRole('button',{name:'Read tracks',exact:true}).click();
  await expect(dialog.getByRole('cell',{name:'7 · MIDI fixture',exact:true})).toBeVisible();
  const shots=path.resolve('../.impeccable/review/bundled');mkdirSync(shots,{recursive:true});
  for (const [lang,width,height] of [['en',1280,900],['zh-TW',1024,768],['ja',1024,768],['ko',1024,768]] as const) {
    await page.setViewportSize({width,height});
    await dialog.locator('.daw-intro select').selectOption(lang);
    await expect(dialog.locator('.daw-engine select')).toHaveValue('bundled');
    await page.screenshot({path:path.join(shots,`${lang}.png`)});
  }
  await dialog.locator('.daw-intro select').selectOption('en');
  await dialog.getByLabel('Role for track 7').selectOption('play');
  await dialog.getByRole('button',{name:'Start conversion',exact:true}).click();
  await expect(dialog.getByRole('status')).toContainText('MIDI preserved');
  await expect(dialog.getByRole('button',{name:'Open generated chart',exact:true})).toHaveCount(0);
  const result=await page.evaluate(async()=>{
    const url='/wails/runtime.js';const {Call}=await import(url);
    return {config:await Call.ByName('main.EditorService.DawSettings'),job:await Call.ByName('main.EditorService.DawStatus')};
  });
  expect(result.config.mode).toBe('bundled');
  expect(result.config.python).toBe('');
  expect(result.config.engineRoot).toBe('');
  expect(readFileSync(path.join(result.job.outputDir,'song.mid')).subarray(0,4).toString()).toBe('MThd');
  expect(readFileSync(source,'utf8')).toBe(xml);
});
