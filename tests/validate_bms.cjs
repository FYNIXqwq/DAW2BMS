// Independent verification with Bemuse's bms parser (development dependency only).
// node tests/validate_bms.cjs <chart-directory> <path-to-bms-npm-package>
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(process.argv[2]);
const BMS = require(path.resolve(process.argv[3]));
const report = JSON.parse(fs.readFileSync(path.join(root, 'export_report.json'), 'utf8'));
const mapping = JSON.parse(fs.readFileSync(path.join(root, 'mapping.json'), 'utf8'));
const text = fs.readFileSync(path.join(root, report.chart), 'utf8');
const compiled = BMS.Compiler.compile(text);
assert.equal(compiled.warnings.length, 0, JSON.stringify(compiled.warnings));
const objects = compiled.chart.objects.all();
const parsedNotes = BMS.Notes.fromBMSChart(compiled.chart).all();
const timing = BMS.Timing.fromBMSChart(compiled.chart);
assert.equal(objects.length, mapping.events.length);
assert.equal(parsedNotes.length, mapping.events.length);
const expected = new Map();
for (const event of mapping.events) {
  const key = [event.bms_tick, event.bms_channel, event.wav_id].join(':');
  expected.set(key, (expected.get(key) || 0) + 1);
}
let maxTimeError = 0;
for (const object of objects) {
  const beat = (object.measure + object.fraction) * 4;
  const tick = Math.round(beat * report.ppq);
  assert.ok(Math.abs(beat * report.ppq - tick) < 1e-9);
  const key = [tick, object.channel, object.value].join(':');
  assert.ok(expected.get(key) > 0, 'Unexpected or duplicated event ' + key);
  expected.set(key, expected.get(key) - 1);
  maxTimeError = Math.max(maxTimeError, Math.abs(timing.beatToSeconds(beat) - tick / report.ppq * 60 / report.bpm));
}
assert.ok([...expected.values()].every(n => n === 0));
assert.ok(maxTimeError < 1e-9);
for (const definition of mapping.definitions) {
  assert.equal(compiled.chart.headers.get('wav' + definition.wav_id), definition.file);
  assert.ok(fs.existsSync(path.join(root, definition.file)));
}
const result = {status: 'passed', parser: 'bms', version: require(path.resolve(process.argv[3], 'package.json')).version,
  audioEvents: objects.length, playableNotes: objects.filter(o => o.channel !== '01').length,
  bgmEvents: objects.filter(o => o.channel === '01').length, wavDefinitions: mapping.definitions.length,
  compilerWarnings: compiled.warnings, maxTimingErrorSeconds: maxTimeError,
  playerGuiTested: false};
fs.writeFileSync(path.join(root, 'external_validation.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result));
