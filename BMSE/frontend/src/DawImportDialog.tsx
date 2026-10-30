import { useEffect, useRef, useState } from "react";
import { api, desktop } from "./api";
import {
  dawLanguage,
  initialDawRequest,
  initialRoles,
  roleSelection,
} from "./daw";
import type { DawConfig, DawPreview, DawJob, DawRole, DawRequest } from "./daw";
import translations from "./daw-locales.json";

export default function DawImportDialog({
  onOpen,
  onBusy,
  initialSource = "",
}: {
  onOpen: (id: string) => Promise<boolean>;
  onBusy: (value: boolean) => void;
  initialSource?: string;
}) {
  const [config, setConfig] = useState<DawConfig>({
    python: "",
    engineRoot: "",
    language: "system",
  });
  const [request, setRequest] = useState<DawRequest>({
    ...initialDawRequest,
    source: initialSource,
  });
  const [preview, setPreview] = useState<DawPreview | null>(null);
  const [roles, setRoles] = useState<Record<number, Record<number, DawRole>>>(
    {},
  );
  const [job, setJob] = useState<DawJob | null>(null),
    [working, setWorking] = useState(true),
    [error, setError] = useState("");
  const [configOpen, setConfigOpen] = useState(false),
    [resources, setResources] = useState("");
  const [reading, setReading] = useState(false);
  const alive = useRef(true),
    log = useRef<HTMLTextAreaElement>(null),
    followLog = useRef(true);
  const language = dawLanguage(
    config.language,
    config.systemLanguage || navigator.language,
  );
  const t = (key: string, params: Record<string, string | number> = {}) =>
    (
      (translations as Record<string, Record<string, string>>)[language]?.[
        key
      ] ?? key
    ).replace(/\{(\w+)\}/g, (all, name) => String(params[name] ?? all));
  const running = job?.status === "running",
    locked = working || running;
  const arrangement = preview?.arrangements.find(
    (a) => a.id === request.arrangement,
  );
  const tracks = arrangement?.tracks ?? [],
    choices = roles[request.arrangement] ?? {};
  const selected = roleSelection(tracks, choices);
  const counts = {
    play: selected.playTracks.length,
    exclude: selected.excludeTracks.length,
    bgm:
      tracks.length -
      selected.playTracks.length -
      selected.excludeTracks.length,
  };
  const message = (value: unknown) => {
    const raw = String(value instanceof Error ? value.message : value);
    for (const code of [
      "DAW_ENGINE",
      "DAW_BUNDLE",
      "DAW_PROTOCOL",
      "DAW_BUSY",
      "DAW_INPUT",
      "DAW_CONFIG",
      "DAW_DESKTOP",
    ])
      if (raw.includes(code)) return t(code) + "\n" + raw;
    return raw;
  };
  const run = async (fn: () => Promise<void>) => {
    setWorking(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      if (alive.current) {
        setError(message(e));
        if (String(e).includes("DAW_ENGINE") || String(e).includes("DAW_BUNDLE")) setConfigOpen(true);
      }
    } finally {
      if (alive.current) setWorking(false);
    }
  };
  useEffect(() => {
    alive.current = true;
    void Promise.all([api.dawSettings(), api.dawStatus()])
      .then(([cfg, current]) => {
        if (!alive.current) return;
        const savedLanguage = localStorage.getItem("bmse-daw-language");
        setConfig({ ...cfg, language: savedLanguage || cfg.language });
        if (cfg.mode !== "bundled" && !cfg.python) setConfigOpen(true);
        if (current && (current.status === "running" || !initialSource)) {
          setJob(current);
          setRequest((r) => ({ ...r, source: current.source }));
        }
      })
      .catch((e) => {
        if (alive.current) {
          setError(String(e));
          setConfigOpen(true);
        }
      })
      .finally(() => {
        if (alive.current) setWorking(false);
      });
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    onBusy(Boolean(locked));
    return () => onBusy(false);
  }, [locked]);
  useEffect(() => {
    if (!running) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await api.dawStatus();
        if (!disposed && current?.id === job.id) setJob(current);
      } catch (e) {
        if (!disposed) setError(String(e));
      }
      if (!disposed) timer = setTimeout(poll, 500);
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [running, job?.id]);
  useEffect(() => {
    if (log.current && followLog.current)
      log.current.scrollTop = log.current.scrollHeight;
  }, [job?.logs]);
  const field = <K extends keyof DawRequest>(key: K, value: DawRequest[K]) =>
    setRequest((r) => ({ ...r, [key]: value }));
  const source = (path: string) => {
    field("source", path);
    setPreview(null);
    setRoles({});
    setJob(null);
  };
  const inspect = () => {
    setReading(true);
    return run(async () => {
      await api.dawSaveSettings(config);
      const result = await api.dawInspect(request.source, language);
      if (!alive.current) return;
      const keep =
        preview?.sha256 === result.sha256 && preview.path === result.path;
      setPreview(result);
      if (!keep)
        setRoles(
          Object.fromEntries(
            result.arrangements.map((a) => [a.id, initialRoles(a.tracks)]),
          ),
        );
      setRequest((r) => ({
        ...r,
        source: result.path,
        sourceHash: result.sha256,
        arrangement:
          keep && result.arrangements.some((a) => a.id === r.arrangement)
            ? r.arrangement
            : (result.arrangements[0]?.id ?? 0),
      }));
      setJob(null);
    }).finally(() => {
      if (alive.current) setReading(false);
    });
  };
  const assign = (id: number, role: DawRole) =>
    setRoles((r) => ({
      ...r,
      [request.arrangement]: { ...(r[request.arrangement] ?? {}), [id]: role },
    }));
  const all = (role: DawRole) =>
    setRoles((r) => ({
      ...r,
      [request.arrangement]: Object.fromEntries(
        tracks.map((track) => [track.id, track.supported ? role : "exclude"]),
      ),
    }));
  const start = () =>
    run(async () => {
      if (!preview || tracks.length === selected.excludeTracks.length)
        throw Error(t("Include at least one note track."));
      await api.dawSaveSettings(config);
      const current = await api.dawStart({
        ...request,
        ...selected,
        source: preview.path,
        sourceHash: preview.sha256,
        language,
        resourceDirs: resources
          .split(/\r?\n/)
          .map((s) => s.trim())
          .filter(Boolean),
      });
      if (alive.current) setJob(current);
    });
  const browse = (kind: string, apply: (path: string) => void) =>
    run(async () => {
      const path = await api.dawPick(kind);
      if (path && alive.current) apply(path);
    });
  const numeric = (
    key: keyof DawRequest,
    label: string,
    min: number,
    max: number,
    step = "any",
  ) => (
    <label className="field">
      <span>{t(label)}</span>
      <input
        aria-label={t(label)}
        type="number"
        min={min}
        max={max}
        step={step}
        value={String(request[key])}
        disabled={locked}
        onChange={(e) => field(key, Number(e.target.value))}
      />
    </label>
  );
  const pathField = (
    label: string,
    value: string,
    change: (v: string) => void,
    kind: string,
    placeholder = "",
  ) => (
    <div className="daw-path">
      <label htmlFor={"daw-" + label.replace(/\W/g, "-")}>{t(label)}</label>
      <input
        id={"daw-" + label.replace(/\W/g, "-")}
        aria-label={t(label)}
        value={value}
        placeholder={t(placeholder)}
        disabled={locked}
        onChange={(e) => change(e.target.value)}
      />
      <button
        type="button"
        disabled={locked || !desktop}
        onClick={() => void browse(kind, change)}
      >
        {t("Browse…")}
      </button>
    </div>
  );
  const stateText = job
    ? job.cancelRequested && running
      ? t("Stopping…")
      : t(
          (
            {
              complete: "Conversion complete",
              midi_only: "MIDI preserved",
              cancelled: "Conversion stopped",
              error: "Conversion failed",
              running: "Converting…",
            } as Record<string, string>
          )[job.status] ?? job.status,
        )
    : t("Choose tracks to import");
  return (
    <section className="daw-import" aria-label={t("Import DAW project")}>
      <div className="daw-intro">
        <p>{t("Import workflow")}</p>
        <label>
          {t("Language")}{" "}
          <select
            aria-label={t("Language")}
            value={config.language}
            disabled={locked}
            onChange={(e) => {
              localStorage.setItem("bmse-daw-language", e.target.value);
              setConfig((c) => ({ ...c, language: e.target.value }));
            }}
          >
            <option value="system">{t("System default")}</option>
            <option value="zh-TW">繁體中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
            <option value="ko">한국어</option>
          </select>
        </label>
      </div>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {pathField("FLP / ALS project file", request.source, source, "source")}
      {pathField(
        "Output location",
        request.outputParent,
        (v) => field("outputParent", v),
        "output",
        "Default output location",
      )}
      <details
        className="daw-engine"
        open={configOpen}
        onToggle={(e) => setConfigOpen(e.currentTarget.open)}
      >
        <summary>{t("Conversion engine")}</summary>
        <label className="field daw-engine-mode">
          <span>{t("Engine mode")}</span>
          <select
            aria-label={t("Engine mode")}
            value={config.mode || "python"}
            disabled={locked}
            onChange={(e) => {
              setConfig((c) => ({ ...c, mode: e.target.value as "bundled" | "python" }));
              setPreview(null);
            }}
          >
            <option value="bundled">{t("Built-in engine")}</option>
            <option value="python">{t("External Python")}</option>
          </select>
        </label>
        {config.mode === "bundled" ? (
          <p className={config.bundledAvailable ? "hint" : "inline-error"} role={config.bundledAvailable ? undefined : "alert"}>
            {t(config.bundledAvailable ? "Built-in engine help" : "DAW_BUNDLE")}
          </p>
        ) : <>
        <p className="hint">{t("Engine setup help")}</p>
        {pathField(
          "Python executable",
          config.python,
          (v) => {
            setConfig((c) => ({ ...c, python: v }));
            setPreview(null);
          },
          "python",
        )}
        {pathField(
          "DAW2BMS folder",
          config.engineRoot,
          (v) => {
            setConfig((c) => ({ ...c, engineRoot: v }));
            setPreview(null);
          },
          "engine",
        )}
        </>}
      </details>
      <div className="daw-track-actions">
        <button
          disabled={locked || !request.source || !desktop}
          onClick={() => void inspect()}
        >
          {t(reading ? "Reading tracks…" : "Read tracks")}
        </button>
        {preview && (
          <label>
            {t("Arrangement")}{" "}
            <select
              aria-label={t("Arrangement")}
              value={request.arrangement}
              disabled={locked}
              onChange={(e) => field("arrangement", Number(e.target.value))}
            >
              {preview.arrangements.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.id} · {a.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="hint">
          {t("{p0} playable · {p1} BGM · {p2} excluded", {
            p0: counts.play,
            p1: counts.bgm,
            p2: counts.exclude,
          })}
        </span>
      </div>
      <div className="daw-track-list">
        <table>
          <thead>
            <tr>
              <th>{t("Track")}</th>
              <th>{t("Notes")}</th>
              <th>{t("Role")}</th>
            </tr>
          </thead>
          <tbody>
            {tracks.length ? (
              tracks.map((track) => (
                <tr
                  key={track.id}
                  className={track.supported ? "" : "daw-unavailable"}
                >
                  <td title={track.name}>
                    {track.id} · {track.name}
                  </td>
                  <td>{track.notes}</td>
                  <td>
                    <select
                      aria-label={t("Role for track {p0}", { p0: track.id })}
                      disabled={locked || !track.supported}
                      value={
                        choices[track.id] ??
                        (track.supported ? "bgm" : "exclude")
                      }
                      onChange={(e) =>
                        assign(track.id, e.target.value as DawRole)
                      }
                    >
                      <option value="play">{t("Playable notes")}</option>
                      <option value="bgm">BGM</option>
                      <option value="exclude">{t("Exclude")}</option>
                    </select>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={3} className="hint">
                  {t(
                    "Read tracks, then choose playable notes, BGM or exclude. BGM keeps sound without using keys.",
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="button-row">
        <button disabled={locked || !tracks.length} onClick={() => all("bgm")}>
          {t("All BGM")}
        </button>
        <button disabled={locked || !tracks.length} onClick={() => all("play")}>
          {t("All playable")}
        </button>
        <span className="hint">
          {t(
            "Tracks default to BGM. Unsupported or muted content is excluded.",
          )}
        </span>
      </div>
      {request.source.toLowerCase().endsWith(".als") && (
        <label className="check-line">
          <input
            type="checkbox"
            checked={request.abletonRender}
            disabled={locked}
            onChange={(e) => field("abletonRender", e.target.checked)}
          />
          {t("Render ALS with Ableton (uses the desktop)")}
        </label>
      )}
      {request.abletonRender &&
        request.source.toLowerCase().endsWith(".als") && (
          <p className="hint">
            {t(
              "Ableton rendering uses the foreground desktop. Save your Set first. Missing or unsupported devices retain MIDI.",
            )}
          </p>
        )}
      <details>
        <summary>{t("Advanced settings")}</summary>
        <div className="daw-options">
          <label className="field">
            <span>{t("Chart title")}</span>
            <input
              aria-label={t("Chart title")}
              value={request.title}
              disabled={locked}
              onChange={(e) => field("title", e.target.value)}
            />
          </label>
          <label className="field">
            <span>{t("Artist")}</span>
            <input
              aria-label={t("Artist")}
              value={request.artist}
              disabled={locked}
              onChange={(e) => field("artist", e.target.value)}
            />
          </label>
          {numeric("initialTail", "Initial tail probe", 0.1, 120)}
          {numeric("maxTail", "Maximum tail probe", 0.1, 1200)}
          {numeric("maxAttempts", "Maximum attempts", 1, 20, "1")}
          {numeric("thresholdDB", "Silence threshold", -120, -20)}
          {numeric("timeout", "Render timeout", 1, 7200)}
          {numeric("leadInBars", "Lead-in", 0, 998, "1")}
        </div>
        {pathField(
          "FL Studio executable",
          request.flExe,
          (v) => field("flExe", v),
          "fl",
          "Automatic detection",
        )}
        {pathField(
          "Ableton Live",
          request.abletonExe,
          (v) => field("abletonExe", v),
          "ableton",
          "Automatic detection",
        )}
        <label className="field">
          <span>{t("Extra resource folders")}</span>
          <textarea
            aria-label={t("Extra resource folders")}
            rows={2}
            value={resources}
            disabled={locked}
            onChange={(e) => setResources(e.target.value)}
          />
        </label>
        <label className="check-line">
          <input
            type="checkbox"
            checked={request.deduplicate}
            disabled={locked}
            onChange={(e) => field("deduplicate", e.target.checked)}
          />
          {t("Reuse identical keysounds")}
        </label>
      </details>
      <div className="daw-status" role="status">
        <strong>{stateText}</strong>
        {running && (
          <span>{job.stage ? `${job.stage}/3` : t("Preparing")}</span>
        )}
      </div>
      {job && (
        <>
          <textarea
            className="daw-log"
            aria-label={t("Log")}
            readOnly
            ref={log}
            value={job.logs.map((l) => l.message).join("\n")}
            onScroll={() => {
              if (log.current)
                followLog.current =
                  log.current.scrollHeight -
                    log.current.scrollTop -
                    log.current.clientHeight <
                  32;
            }}
          />
          {job.error && (
            <p className="inline-error" role="alert">
              {message(job.error)}
            </p>
          )}
          {job.result && (
            <p>
              {t("Result counts", {
                p0: job.result.playable_notes,
                p1: job.result.bgm_events,
                p2: job.result.midi_only_notes,
              })}
              {!job.result.audio_complete && " " + t("Incomplete audio notice")}
            </p>
          )}
          <p className="daw-output" title={job.outputDir}>
            {job.outputDir}
          </p>
        </>
      )}
      <p className="hint">{t("Test chart notice")}</p>
      <div className="dialog-buttons daw-buttons">
        <button
          disabled={
            locked ||
            !preview ||
            !tracks.length ||
            counts.exclude === tracks.length
          }
          onClick={() => void start()}
        >
          {t("Start conversion")}
        </button>
        {running && (
          <button
            disabled={Boolean(job.cancelRequested)}
            onClick={() =>
              void run(async () => {
                await api.dawCancel(job.id);
                setJob(await api.dawStatus());
              })
            }
          >
            {t("Stop after this step")}
          </button>
        )}
        {job && (
          <button
            disabled={working || running}
            onClick={() => void run(() => api.dawOpenOutput(job.id))}
          >
            {t("Output folder")}
          </button>
        )}
        {job?.status === "complete" && job.result?.chart && (
          <button
            disabled={locked}
            onClick={() =>
              void run(async () => {
                await onOpen(job.id);
              })
            }
          >
            {t("Open generated chart")}
          </button>
        )}
      </div>
    </section>
  );
}
