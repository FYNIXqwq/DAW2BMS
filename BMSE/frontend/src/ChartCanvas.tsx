import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  atTime,
  copy,
  encode,
  eventChannel,
  lanes,
  moveNotes,
  newNote,
  pad,
  starts,
} from "./model";
import type { Chart, Kind, Mode, Note } from "./model";
import { longNotePairs } from "./statistics";
import { color as themeColor, laneTheme } from "./legacy";
import type { Ini } from "./legacy";

interface Props {
  theme: Ini;
  scratch2: string;
  laneBackground: boolean;
  readOnly?: boolean;
  lockY?: boolean;
  doc: Chart;
  selected: Set<string>;
  setSelected: (s: Set<string>) => void;
  commit: (d: Chart) => void;
  mode: Mode;
  kind: Kind;
  value: number;
  grid: number;
  zoom: number;
  laneZoom: number;
  player: string;
  keys: number;
  scratch: string;
  bgm: number;
  measure: number;
  jumpToken: number;
  onCursor: (m: number, p: number, c: number) => void;
  onInspect: (n: Note) => void;
  onContext: (x: number, y: number) => void;
  onError: (m: string) => void;
  onZoom: (v: number) => void;
}
type Point = { x: number; y: number; t: number; lane: number };
export default function ChartCanvas(p: Props) {
  const scroll = useRef<HTMLDivElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const [viewport, setViewport] = useState({
    width: 900,
    height: 600,
    x: 0,
    y: 0,
  });
  const [hover, setHover] = useState<Point | null>(null),
    [drag, setDrag] = useState<{
      start: Point;
      current: Point;
      note: boolean;
      ids: Set<string>;
      additive: boolean;
    } | null>(null);
  const ls = useMemo(
    () =>
      lanes(p.player, p.keys, p.scratch, p.bgm, p.scratch2)
        .map((l) => laneTheme(l, p.theme))
        .map((l) => ({
          ...l,
          width: Math.round(l.width * p.laneZoom),
        })),
    [p.player, p.keys, p.scratch, p.scratch2, p.bgm, p.laneZoom, p.theme],
  );
  const a = useMemo(() => starts(p.doc), [p.doc.measures]);
  const maxMeasure = Math.min(
    1000,
    Math.max(
      16,
      p.measure + 8,
      p.doc.notes.reduce((m, n) => Math.max(m, n.measure + 8), 0),
      ...Object.keys(p.doc.measures).map((k) => +k + 8),
    ),
  );
  const scale = 192 * p.zoom,
    totalHeight = a[maxMeasure] * scale + 36;
  const scrollHeight = Math.min(totalHeight, 8_000_000),
    scrollFactor = Math.max(
      1,
      (totalHeight - viewport.height) /
        Math.max(1, scrollHeight - viewport.height),
    );
  const factorRef = useRef(scrollFactor);
  factorRef.current = scrollFactor;
  const columns = useMemo(() => {
    let x = 48;
    return ls.map((l) => {
      const r = { ...l, x };
      x += l.width;
      return r;
    });
  }, [ls]);
  const totalWidth = columns.reduce((s, l) => s + l.width, 48) + 24;
  const time = (n: Note) =>
    a[n.measure] + n.position * (p.doc.measures[n.measure] || 1);
  const toY = (t: number) => totalHeight - 20 - t * scale - viewport.y;

  useLayoutEffect(() => {
    const el = scroll.current!;
    const update = () =>
      setViewport({
        width: el.clientWidth,
        height: el.clientHeight,
        x: el.scrollLeft,
        y: el.scrollTop * factorRef.current,
      });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    update();
    return () => ro.disconnect();
  }, []);
  useLayoutEffect(() => {
    const el = scroll.current!;
    el.scrollTop = Math.max(
      0,
      (totalHeight - 20 - a[p.measure] * scale - el.clientHeight + 32) /
        scrollFactor,
    );
    setViewport((v) => ({
      ...v,
      x: el.scrollLeft,
      y: el.scrollTop * scrollFactor,
    }));
  }, [
    p.jumpToken,
    p.doc.path,
    p.zoom,
    maxMeasure,
    totalHeight,
    viewport.height,
  ]);
  useEffect(() => {
    const el = scroll.current!;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey) {
        event.preventDefault();
        p.onZoom(
          Math.min(3, Math.max(0.25, p.zoom + (event.deltaY < 0 ? 0.1 : -0.1))),
        );
      } else if (event.shiftKey) {
        event.preventDefault();
        el.scrollLeft += event.deltaY || event.deltaX;
      } else if (scrollFactor > 1) {
        event.preventDefault();
        el.scrollTop += event.deltaY / scrollFactor;
        el.scrollLeft += event.deltaX;
      }
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [scrollFactor, p.zoom, p.onZoom]);

  const pairs = useMemo(
    () => longNotePairs(p.doc),
    [p.doc.notes, p.doc.headers.LNOBJ, p.doc.base],
  );

  useLayoutEffect(() => {
    const el = canvas.current!,
      ctx = el.getContext("2d")!,
      dpr = window.devicePixelRatio || 1;
    el.width = viewport.width * dpr;
    el.height = viewport.height * dpr;
    ctx.scale(dpr, dpr);
    ctx.fillStyle = themeColor(p.theme, "Main", "Background", "#000");
    ctx.fillRect(0, 0, viewport.width, viewport.height);
    ctx.font = "11px Consolas, monospace";
    ctx.textBaseline = "middle";
    for (const l of columns) {
      const x = l.x - viewport.x;
      if (x + l.width < 0 || x > viewport.width) continue;
      ctx.fillStyle = p.laneBackground
        ? l.bg
        : themeColor(p.theme, "Main", "Background", "#000");
      ctx.fillRect(x, 25, l.width, viewport.height);
      ctx.strokeStyle = themeColor(p.theme, "Main", "VerticalSub", "#555");
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, viewport.height);
      ctx.stroke();
    }
    ctx.fillStyle = themeColor(p.theme, "Main", "MeasureNum", "#303030");
    ctx.fillRect(-viewport.x, 25, 48, viewport.height);
    for (let m = 0; m < maxMeasure; m++) {
      const y = toY(a[m]),
        nextY = toY(a[m + 1]);
      if (nextY > viewport.height || y < 25) continue;
      for (let j = 1; j < (p.doc.measures[m] || 1) * p.grid - 1e-9; j++) {
        const gy = y - (scale * j) / p.grid;
        if (gy < 25 || gy > viewport.height) continue;
        ctx.strokeStyle =
          j % Math.max(1, p.grid / 4) === 0
            ? themeColor(p.theme, "Main", "GridMain", "#888")
            : themeColor(p.theme, "Main", "GridSub", "#363636");
        ctx.beginPath();
        ctx.moveTo(Math.max(48 - viewport.x, 0), Math.round(gy) + 0.5);
        ctx.lineTo(totalWidth - viewport.x, Math.round(gy) + 0.5);
        ctx.stroke();
      }
      ctx.strokeStyle = themeColor(p.theme, "Main", "MeasureLine", "#ddd");
      ctx.beginPath();
      ctx.moveTo(Math.max(0, 48 - viewport.x), Math.round(y) + 0.5);
      ctx.lineTo(totalWidth - viewport.x, Math.round(y) + 0.5);
      ctx.stroke();
      ctx.fillStyle = m === p.measure ? "#ffff60" : "#eee";
      ctx.fillText(pad(m), 8 - viewport.x, y - 8);
      if ((p.doc.measures[m] || 1) !== 1) {
        ctx.fillStyle = "#bbb";
        ctx.fillText(`${p.doc.measures[m]}×`, 5 - viewport.x, y - 24);
      }
    }
    for (const [head, tail] of pairs) {
      const lane = columns.find((l) => l.channel === head.channel);
      if (!lane) continue;
      const y1 = toY(time(head)),
        y2 = toY(time(tail));
      ctx.fillStyle = themeColor(
        p.theme,
        "KEY_LONGNOTE",
        "ObjectShadow",
        "#267820",
      );
      ctx.fillRect(
        lane.x + 5 - viewport.x,
        Math.max(25, y2),
        lane.width - 10,
        Math.max(0, Math.min(y1, viewport.height) - Math.max(25, y2)),
      );
    }
    for (const n of p.doc.notes) {
      const l = columns.find((l) => l.channel === n.channel);
      if (!l) continue;
      let x = l.x - viewport.x,
        y = toY(time(n));
      if (
        y < 25 ||
        y > viewport.height + 8 ||
        x + l.width < 0 ||
        x > viewport.width
      )
        continue;
      if (drag?.note && drag.ids.has(n.id)) {
        const dx = drag.current.lane - drag.start.lane;
        const index = columns.indexOf(l),
          target =
            columns[Math.max(0, Math.min(columns.length - 1, index + dx))];
        x = target.x - viewport.x;
        y -= (drag.current.t - drag.start.t) * scale;
      }
      const color =
        n.kind === "long"
          ? themeColor(p.theme, "KEY_LONGNOTE", "ObjectLight", "#69d264")
          : n.kind === "mine"
            ? themeColor(p.theme, "KEY_MINE", "ObjectLight", "#ff55cc")
            : l.color;
      ctx.fillStyle = color;
      if (n.kind === "invisible") {
        ctx.strokeStyle = color;
        ctx.strokeRect(x + 2, y - 9, l.width - 4, 9);
      } else {
        ctx.fillRect(x + 2, y - 9, l.width - 4, 9);
        ctx.fillStyle = "#ffffff88";
        ctx.fillRect(x + 2, y - 9, l.width - 4, 1);
      }
      ctx.fillStyle = n.kind === "invisible" ? color : "#000";
      ctx.textAlign = "center";
      ctx.fillText(
        eventChannel(n.channel)
          ? String(n.value)
          : encode(n.value, n.kind === "mine" ? 36 : p.doc.base),
        x + l.width / 2,
        y - 4,
      );
      if (p.selected.has(n.id)) {
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.strokeRect(x + 1, y - 11, l.width - 2, 13);
        ctx.lineWidth = 1;
      }
    }
    ctx.textAlign = "left";
    if (hover && p.mode === "write") {
      const l = columns[hover.lane];
      if (l) {
        const pos = atTime(p.doc, hover.t, p.grid),
          y = toY(
            a[pos.measure] + pos.position * (p.doc.measures[pos.measure] || 1),
          );
        ctx.strokeStyle = "#fff";
        ctx.strokeRect(l.x + 1 - viewport.x, y - 10, l.width - 2, 10);
      }
    }
    if (drag && !drag.note && p.mode === "select") {
      ctx.fillStyle = "#4488dd33";
      ctx.strokeStyle = "#8cbfff";
      ctx.fillRect(
        drag.start.x,
        drag.start.y,
        drag.current.x - drag.start.x,
        drag.current.y - drag.start.y,
      );
      ctx.strokeRect(
        drag.start.x,
        drag.start.y,
        drag.current.x - drag.start.x,
        drag.current.y - drag.start.y,
      );
    }
    ctx.fillStyle = "#dddddd";
    ctx.fillRect(0, 0, viewport.width, 25);
    ctx.fillStyle = "#111";
    ctx.fillText("#", 17 - viewport.x, 12);
    for (const l of columns) {
      const x = l.x - viewport.x;
      ctx.fillStyle = "#111";
      ctx.textAlign = "center";
      ctx.fillText(l.label, x + l.width / 2, 12);
      ctx.strokeStyle = "#aaa";
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, 25);
      ctx.stroke();
    }
  }, [
    p.doc,
    p.theme,
    p.laneBackground,
    p.selected,
    p.grid,
    p.measure,
    p.mode,
    viewport,
    columns,
    pairs,
    drag,
    hover,
    totalHeight,
  ]);

  const point = (e: React.PointerEvent): Point => {
    const rect = canvas.current!.getBoundingClientRect(),
      x = e.clientX - rect.left,
      y = e.clientY - rect.top;
    let lane = columns.findIndex(
      (l) => x + viewport.x >= l.x && x + viewport.x < l.x + l.width,
    );
    return {
      x,
      y,
      lane,
      t: Math.max(0, (totalHeight - 20 - y - viewport.y) / scale),
    };
  };
  const hit = (pt: Point) =>
    [...p.doc.notes]
      .reverse()
      .find(
        (n) =>
          columns[pt.lane]?.channel === n.channel &&
          Math.abs(toY(time(n)) - pt.y - 4) < 8,
      );
  const down = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    if (p.readOnly && p.mode !== "select") {
      p.onError("条件源文保护模式：请使用 BMS 文本或展开分支");
      return;
    }
    canvas.current?.focus();
    const pt = point(e);
    if (pt.y < 25 || pt.lane < 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const n = hit(pt);
    let ids = new Set(p.selected);
    if (p.mode === "select" && n) {
      if (e.ctrlKey || e.metaKey)
        ids.has(n.id) ? ids.delete(n.id) : ids.add(n.id);
      else if (!ids.has(n.id)) ids = new Set([n.id]);
      p.setSelected(ids);
    }
    setDrag({
      start: pt,
      current: pt,
      note: !!n,
      ids,
      additive: e.ctrlKey || e.metaKey,
    });
  };
  const up = (e: React.PointerEvent) => {
    if (!drag || e.button !== 0) return;
    const pt = point(e);
    const n = hit(drag.start);
    setDrag(null);
    if (pt.lane < 0) return;
    if (p.mode === "write") {
      if (n && Math.abs(pt.y - drag.start.y) < 3) {
        p.setSelected(new Set([n.id]));
        p.onInspect(n);
        return;
      }
      const ch = columns[pt.lane].channel;
      const value = eventChannel(ch)
        ? ch === 8
          ? Number(p.doc.headers.BPM || 130)
          : ch === 9
            ? 48
            : 1
        : p.value;
      const note = newNote(p.doc, pt.t, ch, value, p.kind, p.grid);
      if (
        !p.doc.notes.some(
          (x) =>
            x.measure === note.measure &&
            x.position === note.position &&
            x.channel === ch &&
            x.kind === note.kind,
        )
      ) {
        const next = copy(p.doc);
        next.notes.push(note);
        p.commit(next);
        p.setSelected(new Set([note.id]));
        if (eventChannel(ch)) p.onInspect(note);
      }
    } else if (p.mode === "delete") {
      if (n) {
        p.commit({ ...p.doc, notes: p.doc.notes.filter((x) => x.id !== n.id) });
        p.setSelected(new Set());
      }
    } else if (drag.note) {
      if (p.readOnly) return;
      if (Math.abs(pt.y - drag.start.y) > 3 || pt.lane !== drag.start.lane)
        p.commit(
          moveNotes(
            p.doc,
            drag.ids,
            e.shiftKey || p.lockY ? 0 : pt.t - drag.start.t,
            pt.lane - drag.start.lane,
            ls,
            p.grid,
            n?.id,
          ),
        );
    } else {
      const ids = drag.additive ? new Set(p.selected) : new Set<string>();
      for (const x of p.doc.notes) {
        const l = columns.findIndex((l) => l.channel === x.channel),
          t = time(x);
        if (
          l >= Math.min(pt.lane, drag.start.lane) &&
          l <= Math.max(pt.lane, drag.start.lane) &&
          t >= Math.min(pt.t, drag.start.t) &&
          t <= Math.max(pt.t, drag.start.t)
        )
          ids.add(x.id);
      }
      p.setSelected(ids);
    }
  };
  return (
    <div className="chart-region">
      <div
        className="chart-scroll"
        ref={scroll}
        onScroll={(e) => {
          const el = e.currentTarget;
          setViewport((v) => ({
            ...v,
            x: el.scrollLeft,
            y: el.scrollTop * scrollFactor,
          }));
        }}
      >
        <div
          style={{
            width: Math.max(totalWidth, viewport.width),
            height: scrollHeight,
          }}
        >
          <canvas
            ref={canvas}
            aria-label="谱面编辑区：F2 选择，F3 写入，F4 删除；方向键移动所选音符"
            tabIndex={0}
            style={{ width: viewport.width, height: viewport.height }}
            onPointerDown={down}
            onPointerUp={up}
            onPointerCancel={() => setDrag(null)}
            onPointerMove={(e) => {
              const pt = point(e);
              setHover(pt);
              if (drag) setDrag({ ...drag, current: pt });
              const pos = atTime(p.doc, pt.t, p.grid);
              p.onCursor(
                pos.measure,
                pos.position,
                columns[pt.lane]?.channel || 0,
              );
            }}
            onPointerLeave={() => {
              if (!drag) setHover(null);
            }}
            onDoubleClick={(e) => {
              const n = hit(point(e as unknown as React.PointerEvent));
              if (n) p.onInspect(n);
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              const n = hit(point(e as unknown as React.PointerEvent));
              if (n && !p.selected.has(n.id)) p.setSelected(new Set([n.id]));
              p.onContext(e.clientX, e.clientY);
            }}
          />
        </div>
      </div>
    </div>
  );
}
