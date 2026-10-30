import { useEffect, useState } from "react";
import { api } from "./api";
import type { Chart } from "./model";
export default function BranchesDialog({
  source,
  onApply,
  onClose,
  onBusy,
}: {
  source: string;
  onApply: (d: Chart) => void;
  onClose: () => void;
  onBusy: (value: boolean) => void;
}) {
  const [branches, setBranches] = useState<
      { line: number; maximum: number; fixed: number; kind: string }[]
    >([]),
    [choices, setChoices] = useState<Record<number, number>>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    void api
      .branches(source)
      .then((r) => {
        if (active) setBranches(r);
      })
      .catch((e) => setError(String(e)));
    return () => {
      active = false;
    };
  }, [source]);
  return (
    <>
      <p>
        选择每个随机块的值，生成可视化编辑的独立谱面。原始条件定义保持在原文件中。
      </p>
      {branches.map((b) => (
        <label className="field" key={b.line}>
          <span>
            第 {b.line} 行 {b.kind}
          </span>
          <input
            aria-label={`分支 ${b.line}`}
            type="number"
            min={1}
            max={b.maximum}
            disabled={!!b.fixed}
            value={b.fixed || choices[b.line] || 1}
            onChange={(e) =>
              setChoices({ ...choices, [b.line]: +e.target.value })
            }
          />
          <span>1–{b.maximum}</span>
        </label>
      ))}
      {!branches.length && <p>没有随机或条件分支。</p>}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <div className="dialog-buttons">
        <button
          disabled={busy || !branches.length}
          onClick={async () => {
            setBusy(true);
            onBusy(true);
            try {
              const d = await api.resolveBranches(source, choices);
              d.path = "";
              onApply(d);
              onClose();
            } catch (e) {
              setError(String(e));
            } finally {
              setBusy(false);
              onBusy(false);
            }
          }}
        >
          生成独立谱面
        </button>
        <button disabled={busy} onClick={onClose}>
          取消
        </button>
      </div>
    </>
  );
}
