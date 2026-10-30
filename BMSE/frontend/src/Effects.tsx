import { useEffect, useRef } from "react";
import staff from "./legacy/spec/staff.txt?raw";
import mascot from "./legacy/siroani.gif";

export default function Effects({
  effect,
  onClose,
}: {
  effect: string;
  onClose: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (
      !effect ||
      effect === "STAFFROLL" ||
      effect === "BLUESCREEN" ||
      effect === "SIROMARU2"
    )
      return;
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext("2d")!;
    let frame = 0,
      id = 0;
    const img = new Image();
    img.src = mascot;
    const draw = () => {
      c.width = c.clientWidth;
      c.height = c.clientHeight;
      frame++;
      ctx.clearRect(0, 0, c.width, c.height);
      for (let i = 0; i < 60; i++) {
        const x = (i * 83 + Math.sin(frame / 30 + i) * 20) % c.width,
          y = (i * 47 + frame * (1 + (i % 3)) * 0.5) % c.height;
        if (effect.startsWith("SIROMARU") && img.complete)
          ctx.drawImage(img, x, y, 32, 32);
        else {
          ctx.fillStyle = "#ffffffa0";
          ctx.beginPath();
          ctx.arc(x, y, 1 + (i % 3), 0, Math.PI * 2);
          ctx.fill();
        }
      }
      id = requestAnimationFrame(draw);
    };
    id = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(id);
  }, [effect]);
  if (!effect) return null;
  return (
    <div
      className={`effects ${effect === "BLUESCREEN" ? "blue-screen" : ""}`}
      aria-label="彩蛋效果"
    >
      <button aria-label="关闭彩蛋" onClick={onClose}>
        关闭
      </button>
      {effect === "STAFFROLL" ? (
        <pre className="staff-roll">{staff}</pre>
      ) : effect === "BLUESCREEN" ? (
        <div>
          <h2>BMSE · Blue screen</h2>
          <p>这是原版彩蛋效果，谱面与操作历史不受影响。</p>
          <p>关闭即可继续编辑。</p>
        </div>
      ) : effect === "SIROMARU2" ? (
        <img className="mascot-bounce" src={mascot} alt="Siromaru" />
      ) : (
        <canvas ref={canvas} />
      )}
    </div>
  );
}
