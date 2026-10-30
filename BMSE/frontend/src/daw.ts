export interface DawConfig {
  mode?: "bundled" | "python";
  bundledAvailable?: boolean;
  python: string;
  engineRoot: string;
  language: string;
  systemLanguage?: string;
}
export interface DawTrack {
  id: number;
  name: string;
  notes: number;
  supported: boolean;
}
export interface DawPreview {
  path: string;
  sha256: string;
  daw: string;
  arrangements: { id: number; name: string; tracks: DawTrack[] }[];
}
export type DawRole = "play" | "bgm" | "exclude";
export interface DawResult {
  status: string;
  output_directory: string;
  chart: string;
  midi: string;
  fallback_midi: string;
  audio_complete: boolean;
  playable_notes: number;
  bgm_events: number;
  midi_only_notes: number;
}
export interface DawJob {
  id: string;
  status: string;
  source: string;
  outputDir: string;
  stage: number;
  logs: { message: string; level: string }[];
  result: DawResult | null;
  error: string;
  cancelRequested: boolean;
}
export interface DawRequest {
  source: string;
  sourceHash: string;
  outputParent: string;
  language: string;
  arrangement: number;
  playTracks: number[];
  excludeTracks: number[];
  abletonRender: boolean;
  flExe: string;
  abletonExe: string;
  title: string;
  artist: string;
  initialTail: number;
  maxTail: number;
  maxAttempts: number;
  thresholdDB: number;
  timeout: number;
  leadInBars: number;
  deduplicate: boolean;
  resourceDirs: string[];
}
export const initialDawRequest: DawRequest = {
  source: "",
  sourceHash: "",
  outputParent: "",
  language: "en",
  arrangement: 0,
  playTracks: [],
  excludeTracks: [],
  abletonRender: false,
  flExe: "",
  abletonExe: "",
  title: "",
  artist: "",
  initialTail: 1,
  maxTail: 30,
  maxAttempts: 5,
  thresholdDB: -60,
  timeout: 600,
  leadInBars: 1,
  deduplicate: true,
  resourceDirs: [],
};
export function initialRoles(tracks: DawTrack[]): Record<number, DawRole> {
  return Object.fromEntries(
    tracks.map((t) => [t.id, t.supported ? "bgm" : "exclude"]),
  );
}
export function roleSelection(
  tracks: DawTrack[],
  roles: Record<number, DawRole>,
) {
  const playTracks: number[] = [],
    excludeTracks: number[] = [];
  for (const t of tracks) {
    const role = t.supported ? (roles[t.id] ?? "bgm") : "exclude";
    if (role === "play") playTracks.push(t.id);
    if (role === "exclude") excludeTracks.push(t.id);
  }
  return { playTracks, excludeTracks };
}
export function dawLanguage(
  choice: string,
  system = navigator.language,
): string {
  const value = (choice === "system" ? system : choice).toLowerCase();
  return value.startsWith("zh")
    ? "zh-TW"
    : value.startsWith("ja")
      ? "ja"
      : value.startsWith("ko")
        ? "ko"
        : "en";
}
