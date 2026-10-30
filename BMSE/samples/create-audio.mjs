// Deterministic synthetic fixtures. No external recordings or copyrighted music.
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const rate = 22050;
let seed = 7;
function noise() { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 0xffffffff * 2 - 1; }
for (const name of ['kick', 'snare', 'hat', 'tone']) {
 const count = Math.floor(rate * (name === 'tone' ? .7 : .25)), b = Buffer.alloc(44 + count * 2);
 b.write('RIFF'); b.writeUInt32LE(b.length - 8, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(count * 2, 40);
 for (let i = 0; i < count; i++) { const t = i / rate; const v = name === 'kick' ? Math.sin(2 * Math.PI * (50 * t + 2 * (1 - Math.exp(-35 * t)))) * Math.exp(-20 * t) : name === 'snare' ? (noise() * .7 + Math.sin(2 * Math.PI * 180 * t) * .3) * Math.exp(-25 * t) : name === 'hat' ? noise() * Math.exp(-60 * t) : Math.sin(2 * Math.PI * 440 * t) * Math.min(1, t * 200) * Math.exp(-5 * t); b.writeInt16LE(Math.round(v * 12000), 44 + i * 2); }
 writeFileSync(fileURLToPath(new URL(`${name}.wav`, import.meta.url)), b);
}
