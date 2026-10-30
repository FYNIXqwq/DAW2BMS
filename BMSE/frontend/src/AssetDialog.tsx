import { useEffect, useState } from "react";
import { api, desktop } from "./api";
import type { AssetPlan } from "./api";
import type { Chart } from "./model";

export default function AssetDialog({
  doc,
  journal,
  onResult,
  onClose,
  onBusy,
  renameSource = "",
}: {
  doc: Chart;
  journal: string;
  onResult: (d: Chart, journal: string) => Promise<void>;
  onClose: () => void;
  onBusy: (value: boolean) => void;
  renameSource?: string;
}) {
  const [mode, setMode] = useState(renameSource ? "rename-one" : "cleanup"),
    [plan, setPlan] = useState<AssetPlan | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [renameTarget, setRenameTarget] = useState(
    renameSource.split(/[\\/]/).pop() || "",
  );
  useEffect(() => setPlan(null), [mode, renameTarget]);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      onBusy(false);
    }
  };
  return (
    <>
      <p>
        先生成预览，再执行。清理会将文件移入谱面目录下的
        .bmse-recovery；重命名会同步保存素材引用。两种操作均有恢复记录。
      </p>
      <label className="field">
        <span>操作</span>
        <select
          aria-label="磁盘整理操作"
          value={mode}
          disabled={busy}
          onChange={(e) => setMode(e.target.value)}
        >
          <option value="cleanup">清理未使用素材</option>
          <option value="rename">按编号重命名素材</option>
          {renameSource && <option value="rename-one">重命名所选素材</option>}
        </select>
      </label>
      {mode === "rename-one" && (
        <label className="field">
          <span>新文件名</span>
          <input
            aria-label="新文件名"
            disabled={busy}
            value={renameTarget}
            onChange={(e) => setRenameTarget(e.target.value)}
          />
        </label>
      )}
      <p className="hint">
        扫描同目录所有
        BMS/BME/BML/PMS，保护其他谱面引用的文件。只处理当前目录的素材，不跟随链接，不覆盖已有文件。
      </p>
      <div className="button-row">
        <button
          disabled={busy || !desktop}
          onClick={() =>
            void run(async () =>
              setPlan(
                mode === "rename-one"
                  ? await api.planRename(doc, renameSource, renameTarget)
                  : await api.planAssets(doc, mode),
              ),
            )
          }
        >
          生成操作预览
        </button>
        <button
          disabled={!journal || busy || !desktop}
          onClick={() =>
            void run(async () => {
              const restored = await api.restoreAssets(journal, doc.path);
              await onResult(restored, "");
              onClose();
            })
          }
        >
          恢复上次磁盘操作
        </button>
      </div>
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      {plan && (
        <>
          <p>将处理 {plan.changes.length} 个文件：</p>
          <div className="asset-changes">
            <table className="data-table">
              <thead>
                <tr>
                  <th>原文件</th>
                  <th>处理结果</th>
                </tr>
              </thead>
              <tbody>
                {plan.changes.map((c) => (
                  <tr key={c.from}>
                    <td>{c.from}</td>
                    <td>{c.to || "移入恢复目录"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {plan.warnings.map((w, i) => (
            <p key={i} className="hint">
              {w}
            </p>
          ))}
        </>
      )}
      <div className="dialog-buttons">
        <button
          disabled={busy || !plan?.changes.length}
          onClick={() =>
            void run(async () => {
              const result = await api.applyAssets(plan!.token);
              await onResult(result.document, result.journal);
              onClose();
            })
          }
        >
          执行以上 {plan?.changes.length || 0} 项
        </button>
        <button disabled={busy} onClick={onClose}>
          取消
        </button>
      </div>
    </>
  );
}
