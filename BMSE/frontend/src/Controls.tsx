import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
export function Field({
  label,
  value,
  onChange,
  type = "text",
  min,
  max,
  step,
  disabled = false,
}: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
  min?: number;
  max?: number;
  step?: string;
  disabled?: boolean;
}) {
  const [text, setText] = useState(String(value));
  const cancelBlur = useRef(false);
  useLayoutEffect(() => setText(String(value)), [value]);
  const notify = (element: HTMLElement, value: boolean) => {
    if (element.closest("dialog") || element.closest('[data-view="true"]'))
      return;
    window.dispatchEvent(new CustomEvent("bmse-field-edit", { detail: value }));
  };
  const apply = (e: React.FocusEvent<HTMLInputElement>) => {
    notify(e.currentTarget, false);
    if (cancelBlur.current) {
      cancelBlur.current = false;
      return;
    }
    if (
      type === "number" &&
      (!Number.isFinite(Number(text)) ||
        (min !== undefined && Number(text) < min) ||
        (max !== undefined && Number(text) > max))
    ) {
      setText(String(value));
      return;
    }
    if (text !== String(value)) {
      onChange(text);
      setText(String(value));
    }
  };
  return (
    <label className="field">
      <span>{label}</span>
      <input
        disabled={disabled}
        aria-label={label}
        type={type}
        min={min}
        max={max}
        step={step || "any"}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          notify(e.currentTarget, e.target.value !== String(value));
        }}
        onBlur={apply}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          }
          if (e.key === "Escape") {
            e.stopPropagation();
            cancelBlur.current = true;
            setText(String(value));
            e.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      className={wide ? "wide" : ""}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <header>
        <strong>{title}</strong>
        <button aria-label="关闭对话框" onClick={onClose}>
          ×
        </button>
      </header>
      <div className="dialog-content">{children}</div>
    </dialog>
  );
}
