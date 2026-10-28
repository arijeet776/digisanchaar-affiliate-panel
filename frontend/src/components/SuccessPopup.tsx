import { useEffect, type ReactNode } from "react";

/**
 * Glass popup for success / confirmation messages (replaces the old top-of-page banner).
 * Controlled: render it with `open`, and clear your state in `onClose`.
 * Closes on the × button, a click on the dimmed background, or the Escape key.
 */
export function SuccessPopup({ open, onClose, children, title = "Done", testId }: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  title?: string;
  testId?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="qx-popup-overlay" onClick={onClose}>
      <div className="qx-popup-card" role="dialog" aria-modal="true" aria-label={title} data-testid={testId}
        onClick={(e) => e.stopPropagation()}>
        <button type="button" className="qx-popup-x" aria-label="Close" onClick={onClose}>×</button>
        <div className="qx-popup-title">{title}</div>
        <div className="qx-popup-body">{children}</div>
      </div>
    </div>
  );
}
