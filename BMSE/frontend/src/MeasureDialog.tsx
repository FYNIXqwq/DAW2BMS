import { useState } from "react";
import type { Chart } from "./model";
import { resizeMeasures } from "./model";
import { Field } from "./Controls";
export default function MeasureDialog({
  doc,
  measure,
  onApply,
  onClose,
}: {
  doc: Chart;
  measure: number;
  onApply: (d: Chart) => void;
  onClose: () => void;
}) {
  const [first, setFirst] = useState(measure),
    [last, setLast] = useState(measure),
    [value, setValue] = useState(String(doc.measures[measure] || 1)),
    [error, setError] = useState("");
  return (
    <>
      <Field
        label="起始小节"
        type="number"
        min={0}
        max={999}
        value={first}
        onChange={(v) => setFirst(Math.round(+v))}
      />
      <Field
        label="结束小节"
        type="number"
        min={first}
        max={999}
        value={last}
        onChange={(v) => setLast(Math.round(+v))}
      />
      <Field label="小节长度（倍数或分数）" value={value} onChange={setValue} />
      <p>
        例如 3/4 或
        0.75。音符保持原小节内时间，超出新小节末尾的部分顺延到后续小节；可用撤销恢复。
      </p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-buttons">
        <button
          onClick={() => {
            try {
              const text = value.replace(/\s/g, "");
              if (!/^\d+(?:\.\d+)?(?:\/\d+(?:\.\d+)?)?$/.test(text))
                throw new Error("请输入有效倍数或分数");
              const parts = text.split("/").map(Number),
                ratio = parts[0] / (parts[1] ?? 1);
              onApply(resizeMeasures(doc, first, last, ratio));
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
