import { useEffect, useMemo, useRef, useState } from "react";
import { api, desktop } from "./api";
import { dawLanguage } from "./daw";
import { assignDraft, draftRows, editableDraftIDs } from "./draft";
import { encode } from "./model";
import type { Chart, Lane } from "./model";
import translations from "./daw-locales.json";

export default function DawDraftDialog({
  doc,
  onChange,
  onLocate,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  lanes,
}: {
  doc: Chart;
  onChange: (d: Chart) => void;
  onLocate: (ids: Set<string>) => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  lanes: Lane[];
}) {
  const [language, setLanguage] = useState(
    dawLanguage(localStorage.getItem("bmse-daw-language") || "system"),
  );
  const [track, setTrack] = useState("all"),
    [instrument, setInstrument] = useState("all"),
    [page, setPage] = useState(0);
  const [chosen, setChosen] = useState(new Set<string>()),
    [target, setTarget] = useState("auto");
  const [error, setError] = useState(""),
    [notice, setNotice] = useState<number | null>(null),
    [preview, setPreview] = useState(""),
    [previewing, setPreviewing] = useState("");
  const previewRequest = useRef(0);
  const t = (key: string, params: Record<string, string | number> = {}) =>
    (
      (translations as Record<string, Record<string, string>>)[language]?.[
        key
      ] || key
    ).replace(/\{(\w+)\}/g, (all, k) => String(params[k] ?? all));
  useEffect(() => {
    let alive = true;
    void api
      .dawSettings()
      .then((c) => {
        if (alive)
          setLanguage(
            dawLanguage(
              localStorage.getItem("bmse-daw-language") || c.language,
              c.systemLanguage,
            ),
          );
      })
      .catch(() => {});
    return () => {
      alive = false;
      previewRequest.current++;
    };
  }, []);
  const rows = useMemo(() => draftRows(doc), [doc]);
  const editable = useMemo(() => editableDraftIDs(doc), [doc]);
  const tracks = [
    ...new Map(rows.map((r) => [r.trackId, r.trackName])).entries(),
  ];
  const instruments = [
    ...new Map(
      rows
        .filter((r) => track === "all" || String(r.trackId) === track)
        .map((r) => [String(r.channelId), r.instrumentName]),
    ).entries(),
  ];
  const filtered = rows.filter(
    (r) =>
      (track === "all" || String(r.trackId) === track) &&
      (instrument === "all" || String(r.channelId) === instrument),
  );
  const selected = filtered.filter((r) => chosen.has(r.id) && !r.locked);
  const selectedIDs = new Set(
    selected.flatMap((r) => r.notes.map((n) => n.id)),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 60)),
    current = Math.min(page, pages - 1),
    visible = filtered.slice(current * 60, (current + 1) * 60);
  const keyLanes = lanes.filter(
    (l) =>
      (l.channel >= 37 && l.channel <= 45) ||
      (l.channel >= 73 && l.channel <= 81),
  );
  const autoLanes = keyLanes
    .filter((l) => !["SC", "2SC", "LSC", "RSC", "FOOT"].includes(l.label))
    .map((l) => l.channel);
  const reset = () => {
    setChosen(new Set());
    setPage(0);
    setNotice(null);
    setError("");
    setPreview("");
    previewRequest.current++;
    setPreviewing("");
  };
  const apply = (role: "play" | "bgm", all = false) => {
    setError("");
    setNotice(null);
    try {
      const ids = all ? editable : selectedIDs;
      const next = assignDraft(
        doc,
        ids,
        role,
        target === "auto" ? autoLanes : [Number(target)],
      );
      onChange(next);
      setNotice(ids.size);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const listen = async (value: number) => {
    const request = ++previewRequest.current;
    setError("");
    setPreviewing(encode(value, doc.base));
    setPreview("");
    try {
      const data = await api.material(doc.path, doc.wav[String(value)]);
      if (request === previewRequest.current) setPreview(data);
    } catch (e) {
      if (request === previewRequest.current) setError(String(e));
    } finally {
      if (request === previewRequest.current) setPreviewing("");
    }
  };
  return (
    <section className="daw-draft" aria-label={t("DAW draft")}>
      <div className="daw-intro">
        <p>{t("Draft intro")}</p>
        <label>
          {t("Language")}{" "}
          <select
            aria-label={t("Language")}
            value={language}
            onChange={(e) => {
              setLanguage(e.target.value);
              localStorage.setItem("bmse-daw-language", e.target.value);
            }}
          >
            {[
              ["zh-TW", "繁體中文"],
              ["en", "English"],
              ["ja", "日本語"],
              ["ko", "한국어"],
            ].map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!doc.dawDraft ? (
        <p className="hint">{t("Draft unavailable")}</p>
      ) : (
        <>
          <p className="hint">
            {doc.dawDraft.sourceFile} · {t("Draft source help")}
          </p>
          <div className="draft-filters">
            <label>
              {t("DAW track")}
              <select
                value={track}
                onChange={(e) => {
                  setTrack(e.target.value);
                  setInstrument("all");
                  reset();
                }}
                aria-label={t("DAW track")}
              >
                <option value="all">{t("All tracks")}</option>
                {tracks.map(([id, name]) => (
                  <option key={id} value={id}>
                    {id} · {name || t("Unnamed track")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("Instrument / channel")}
              <select
                value={instrument}
                onChange={(e) => {
                  setInstrument(e.target.value);
                  reset();
                }}
                aria-label={t("Instrument / channel")}
              >
                <option value="all">{t("All instruments")}</option>
                {instruments.map(([id, name]) => (
                  <option key={id} value={id}>
                    {id} · {name || t("Unnamed instrument")}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="draft-selection">
            <button
              onClick={() =>
                setChosen(
                  new Set(filtered.filter((r) => !r.locked).map((r) => r.id)),
                )
              }
              disabled={!filtered.some((r) => !r.locked)}
            >
              {t("Select filtered")}
            </button>
            <button
              onClick={() => setChosen(new Set())}
              disabled={!selected.length}
            >
              {t("Clear selection")}
            </button>
            <span>
              {t("Draft counts", {
                sounds: filtered.length,
                selected: selectedIDs.size,
              })}
            </span>
          </div>
          <div className="draft-table">
            <table>
              <thead>
                <tr>
                  <th>{t("Select")}</th>
                  <th>{t("DAW track")}</th>
                  <th>{t("Instrument / channel")}</th>
                  <th>{t("Sound")}</th>
                  <th>{t("Current use")}</th>
                  <th>{t("Preview")}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={t("Select sound", {
                          id: `${r.trackId}/${r.channelId}/${encode(r.value, doc.base)}`,
                        })}
                        disabled={!!r.locked}
                        checked={chosen.has(r.id) && !r.locked}
                        onChange={(e) =>
                          setChosen((old) => {
                            const next = new Set(old);
                            if (e.target.checked) next.add(r.id);
                            else next.delete(r.id);
                            return next;
                          })
                        }
                      />
                    </td>
                    <td title={r.trackName}>
                      {r.trackId} · {r.trackName || t("Unnamed track")}
                    </td>
                    <td title={r.instrumentName}>
                      {r.channelId} ·{" "}
                      {r.instrumentName || t("Unnamed instrument")}
                    </td>
                    <td title={doc.wav[String(r.value)]}>
                      {encode(r.value, doc.base)} · {t("Pitch")} {r.pitch}
                      <small>
                        {r.notes.length} {t("Occurrences")}
                      </small>
                    </td>
                    <td>
                      {t("Draft roles", { play: r.playable, bgm: r.bgm })}
                      {r.locked > 0 && (
                        <small>{t("Draft locked", { count: r.locked })}</small>
                      )}
                    </td>
                    <td>
                      <button
                        disabled={
                          !desktop || !doc.wav[String(r.value)] || !!previewing
                        }
                        aria-label={t("Preview sound", {
                          id: encode(r.value, doc.base),
                        })}
                        onClick={() => void listen(r.value)}
                      >
                        {t("Preview")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!filtered.length && (
              <p className="hint">{t("No matching sounds")}</p>
            )}
          </div>
          {pages > 1 && (
            <div className="draft-selection">
              <button
                disabled={current === 0}
                onClick={() => setPage(current - 1)}
              >
                {t("Previous")}
              </button>
              <span>
                {current + 1} / {pages}
              </span>
              <button
                disabled={current === pages - 1}
                onClick={() => setPage(current + 1)}
              >
                {t("Next")}
              </button>
            </div>
          )}
          {preview && (
            <audio
              aria-label={t("Keysound preview")}
              controls
              autoPlay
              src={preview}
            />
          )}
          <p className="hint">{t("Draft timing help")}</p>
          <div className="draft-actions">
            <label>
              {t("Target keys")}
              <select
                aria-label={t("Target keys")}
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="auto">{t("Automatic keys")}</option>
                {keyLanes.map((l) => (
                  <option key={l.channel} value={l.channel}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={!selectedIDs.size || !!doc.sourceText}
              onClick={() => apply("play")}
            >
              {t("Move to keys")}
            </button>
            <button
              disabled={!selectedIDs.size || !!doc.sourceText}
              onClick={() => apply("bgm")}
            >
              {t("Move to BGM")}
            </button>
            <button
              disabled={!selectedIDs.size}
              onClick={() => onLocate(selectedIDs)}
            >
              {t("Select in chart")}
            </button>
          </div>
          <div className="draft-selection">
            <button
              disabled={
                !doc.notes.some(
                  (n) => editable.has(n.id) && n.channel < 1297,
                ) || !!doc.sourceText
              }
              onClick={() => apply("bgm", true)}
            >
              {t("All draft sounds to BGM")}
            </button>
            <button
              disabled={!canUndo}
              onClick={() => {
                onUndo();
                setNotice(null);
                setError("");
              }}
            >
              {t("Undo")}
            </button>
            <button
              disabled={!canRedo}
              onClick={() => {
                onRedo();
                setNotice(null);
                setError("");
              }}
            >
              {t("Redo")}
            </button>
          </div>
        </>
      )}
      {notice !== null && (
        <p role="status">{t("Draft applied", { count: notice })}</p>
      )}
      {error && (
        <p className="inline-error" role="alert">
          {t(error)}
        </p>
      )}
      {doc.warnings
        .filter((w) => w.startsWith("DAW_"))
        .map((w, i) => (
          <p className="inline-error" key={i}>
            {t("Draft mapping warning")}
            <small>{w}</small>
          </p>
        ))}
    </section>
  );
}
