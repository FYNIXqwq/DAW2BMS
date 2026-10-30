import { useEffect, useRef, useState } from "react";
import { decode, encode } from "./model";
import type { Chart } from "./model";
import { Field } from "./Controls";

export interface BGA {
  image: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  dx: number;
  dy: number;
}
export function parseBGA(text: string, base: number): BGA {
  const p = text.trim().split(/\s+/);
  const nums = p.slice(1).map(Number);
  return {
    image: decode(p[0] || "01", base) || 1,
    x1: nums[0] || 0,
    y1: nums[1] || 0,
    x2: nums[2] ?? 256,
    y2: nums[3] ?? 256,
    dx: nums[4] || 0,
    dy: nums[5] || 0,
  };
}
export function formatBGA(b: BGA, base: number) {
  if (!Number.isInteger(b.image) || b.image < 1 || b.image >= base ** 2)
    throw new Error("BMP 编号无效");
  for (const k of ["x1", "y1", "x2", "y2", "dx", "dy"] as const)
    if (!Number.isInteger(b[k]) || b[k] < 0 || b[k] > 16384)
      throw new Error("BGA 坐标必须是 0–16384 的整数");
  if (b.x2 < b.x1 || b.y2 < b.y1) throw new Error("裁剪终点必须大于起点");
  return [encode(b.image, base), b.x1, b.y1, b.x2, b.y2, b.dx, b.dy].join(" ");
}
export function drawBGA(
  ctx: CanvasRenderingContext2D,
  image: CanvasImageSource,
  b: BGA,
) {
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, 256, 256);
  const w = Math.max(0, Math.min(256, b.x2 - b.x1)),
    h = Math.max(0, Math.min(256, b.y2 - b.y1));
  if (w && h) ctx.drawImage(image, b.x1, b.y1, w, h, b.dx, b.dy, w, h);
}
export function BGAImage({
  src,
  value,
  base,
}: {
  src: string;
  value: string;
  base: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let valid = true;
    const image = new Image();
    image.onload = () => {
      if (valid && ref.current)
        drawBGA(ref.current.getContext("2d")!, image, parseBGA(value, base));
    };
    image.src = src;
    return () => {
      valid = false;
    };
  }, [src, value, base]);
  return (
    <canvas
      ref={ref}
      width={256}
      height={256}
      aria-label="BGA 裁剪预览"
      style={{ maxWidth: "100%", maxHeight: 130 }}
    />
  );
}
export default function BGAEditor({
  doc,
  id,
  load,
  onApply,
  onClose,
}: {
  doc: Chart;
  id: number;
  load: (name: string) => Promise<string>;
  onApply: (value: string) => void;
  onClose: () => void;
}) {
  const [b, setB] = useState(() =>
      parseBGA(doc.bga[id] || "01 0 0 256 256 0 0", doc.base),
    ),
    [src, setSrc] = useState(""),
    [error, setError] = useState(""),
    [size, setSize] = useState({ w: 256, h: 256 }),
    [grid, setGrid] = useState(true);
  const source = useRef<HTMLCanvasElement>(null),
    target = useRef<HTMLCanvasElement>(null),
    image = useRef<HTMLImageElement | null>(null),
    drag = useRef<{ x: number; y: number; dx: number; dy: number } | null>(
      null,
    );
  useEffect(() => {
    let active = true;
    setError("");
    image.current = null;
    setSrc("");
    const name = doc.bmp[b.image];
    if (!name) {
      setError("这个 BMP 编号未定义图像");
      return;
    }
    void load(name)
      .then((data) => {
        if (active) setSrc(data);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, [b.image, doc.bmp]);
  useEffect(() => {
    let active = true;
    if (!src) return;
    const img = new Image();
    img.onload = () => {
      if (active) {
        image.current = img;
        setSize({ w: img.naturalWidth, h: img.naturalHeight });
      }
    };
    img.onerror = () => setError("无法解码图像");
    img.src = src;
    return () => {
      active = false;
    };
  }, [src]);
  useEffect(() => {
    const img = image.current;
    if (!img || !source.current || !target.current) return;
    const ctx = source.current.getContext("2d")!,
      out = target.current.getContext("2d")!;
    const scale = Math.min(256 / size.w, 256 / size.h);
    ctx.fillStyle = "#202020";
    ctx.fillRect(0, 0, 256, 256);
    ctx.drawImage(img, 0, 0, size.w * scale, size.h * scale);
    ctx.strokeStyle = "#ff4040";
    ctx.lineWidth = 2;
    ctx.strokeRect(
      b.x1 * scale,
      b.y1 * scale,
      (b.x2 - b.x1) * scale,
      (b.y2 - b.y1) * scale,
    );
    drawBGA(out, img, b);
    if (grid) {
      out.strokeStyle = "#ffffff35";
      for (let i = 0; i < 256; i += 32) {
        out.beginPath();
        out.moveTo(i, 0);
        out.lineTo(i, 256);
        out.moveTo(0, i);
        out.lineTo(256, i);
        out.stroke();
      }
    }
  }, [b, size, src, grid]);
  const point = (
    e: React.PointerEvent<HTMLCanvasElement>,
    isSource: boolean,
  ) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const scale = isSource ? Math.min(256 / size.w, 256 / size.h) : 1;
    return {
      x: Math.round(((e.clientX - rect.left) * 256) / rect.width / scale),
      y: Math.round(((e.clientY - rect.top) * 256) / rect.height / scale),
    };
  };
  return (
    <>
      <p>
        BGA {encode(id, doc.base)}
        ：在左侧拖动选择裁剪区域，在右侧拖动调整目标位置。
      </p>
      <div className="bga-canvases">
        <figure>
          <figcaption>
            源图像 {size.w} × {size.h}
          </figcaption>
          <canvas
            ref={source}
            width={256}
            height={256}
            aria-label="BGA 源图像裁剪"
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              const p = point(e, true);
              drag.current = { ...p, dx: 0, dy: 0 };
              setB({ ...b, x1: p.x, y1: p.y, x2: p.x, y2: p.y });
            }}
            onPointerMove={(e) => {
              if (!drag.current) return;
              const p = point(e, true);
              setB({
                ...b,
                x1: Math.max(0, Math.min(p.x, drag.current.x)),
                y1: Math.max(0, Math.min(p.y, drag.current.y)),
                x2: Math.min(size.w, Math.max(p.x, drag.current.x)),
                y2: Math.min(size.h, Math.max(p.y, drag.current.y)),
              });
            }}
            onPointerUp={() => (drag.current = null)}
          />
        </figure>
        <figure>
          <figcaption>输出 256 × 256</figcaption>
          <canvas
            ref={target}
            width={256}
            height={256}
            aria-label="BGA 目标位置"
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              drag.current = { ...point(e, false), dx: b.dx, dy: b.dy };
            }}
            onPointerMove={(e) => {
              if (!drag.current) return;
              const p = point(e, false);
              setB({
                ...b,
                dx: Math.max(0, drag.current.dx + p.x - drag.current.x),
                dy: Math.max(0, drag.current.dy + p.y - drag.current.y),
              });
            }}
            onPointerUp={() => (drag.current = null)}
          />
        </figure>
      </div>
      <div className="bga-fields">
        <Field
          label="BMP"
          value={encode(b.image, doc.base)}
          onChange={(v) => {
            const id = decode(v, doc.base);
            if (Number.isInteger(id) && id > 0 && id < doc.base ** 2)
              setB({ ...b, image: id });
          }}
        />
        {(["x1", "y1", "x2", "y2", "dx", "dy"] as const).map((k) => (
          <Field
            key={k}
            label={k}
            type="number"
            min={0}
            max={16384}
            value={b[k]}
            onChange={(v) => setB({ ...b, [k]: Math.round(+v) })}
          />
        ))}
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={grid}
          onChange={(e) => setGrid(e.target.checked)}
        />
        显示预览网格
      </label>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <div className="dialog-buttons">
        <button
          onClick={() => {
            try {
              onApply(formatBGA(b, doc.base));
              onClose();
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          应用
        </button>
        <button onClick={onClose}>取消</button>
      </div>
    </>
  );
}
