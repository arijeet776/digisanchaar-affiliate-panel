import { Children, cloneElement, isValidElement, useEffect, useId, useRef, type ComponentType, type ReactElement, type ReactNode, type SVGProps } from "react";
import { IconChevronLeft, IconChevronRight, IconClose } from "./Icons";

export function StatusBadge({ status }: { status: string }) {
  // Unknown statuses fall back to the neutral badge style (never to a semantic colour).
  return <span className={`qx-badge ${status}`} data-testid={`status-badge-${status}`}>{status.replace(/_/g, " ")}</span>;
}

interface Metric {
  available: boolean;
  value: number | string | null;
  reason: string | null;
}

export function KpiCard({
  label,
  metric,
  format,
  icon: Icon,
}: {
  label: string;
  metric: Metric;
  format?: (v: number) => string;
  icon?: ComponentType<SVGProps<SVGSVGElement>>;
}) {
  return (
    <div className="qx-kpi-card" data-testid={`kpi-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
      {Icon && (
        <>
          <div className="qx-kpi-icon">
            <Icon width={17} height={17} />
          </div>
          <Icon className="qx-kpi-watermark" aria-hidden="true" />
        </>
      )}
      <div className="qx-kpi-label">{label}</div>
      {metric.available ? (
        <div className="qx-kpi-value">{typeof metric.value === "number" ? (format ? format(metric.value) : metric.value.toLocaleString("en-US")) : metric.value}</div>
      ) : (
        <div className="qx-kpi-value unavailable" title={metric.reason ?? undefined}>
          Not yet available
        </div>
      )}
    </div>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <nav className="qx-pagination" aria-label="Pagination">
      <span aria-live="polite">
        {total === 0 ? "No results" : `${start}–${end} of ${total}`}
      </span>
      <div className="qx-pagination-controls">
        <button className="qx-btn qx-btn-sm" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Previous page">
          <IconChevronLeft width={14} height={14} />
        </button>
        <span style={{ padding: "5px 6px" }}>
          {page} / {totalPages}
        </span>
        <button className="qx-btn qx-btn-sm" disabled={page >= totalPages} onClick={() => onChange(page + 1)} aria-label="Next page">
          <IconChevronRight width={14} height={14} />
        </button>
      </div>
    </nav>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCloseRef.current();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, []);

  return (
    <div className="qx-modal-backdrop" onClick={onClose}>
      <div
        className="qx-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={dialogRef}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="qx-modal-head">
          <div className="qx-modal-title" id={titleId}>{title}</div>
          <button className="qx-icon-btn" onClick={onClose} aria-label="Close dialog">
            <IconClose width={14} height={14} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="qx-error-banner" role="alert">{message}</div>;
}

export function EmptyState({ message, title }: { message: string; title?: string }) {
  return (
    <div className="qx-empty-state">
      {title && <div className="qx-empty-title">{title}</div>}
      {message}
    </div>
  );
}

/** Success / warning / info message in the same shape as ErrorBanner. */
export function Banner({ kind, children }: { kind: "success" | "warning" | "info"; children: ReactNode }) {
  return <div className={`qx-${kind}-banner`} role={kind === "success" ? "status" : undefined}>{children}</div>;
}

/** Standard page heading: title, optional subtitle, optional right-aligned actions. */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="qx-page-header">
      <div>
        <h1 className="qx-page-title">{title}</h1>
        {subtitle && <div className="qx-page-subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="qx-page-actions">{actions}</div>}
    </div>
  );
}

/** Loading placeholder (skeleton). Shows structure only — never invented data. */
export function LoadingState({ variant = "table", rows = 5 }: { variant?: "table" | "kpis" | "text"; rows?: number }) {
  if (variant === "kpis") {
    return (
      <div className="qx-skeleton-kpis" role="status" aria-label="Loading">
        {Array.from({ length: rows }).map((_, i) => <span key={i} className="qx-skeleton qx-skeleton-kpi" />)}
      </div>
    );
  }
  return (
    <div className="qx-skeleton-table" role="status" aria-label="Loading">
      {Array.from({ length: variant === "text" ? 3 : rows }).map((_, i) => (
        <span key={i} className="qx-skeleton" style={{ height: variant === "text" ? 14 : 22, width: variant === "text" ? `${90 - i * 18}%` : "100%" }} />
      ))}
    </div>
  );
}

/** Error panel with an optional retry (the caller supplies the retry action). */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="qx-error-state" role="alert">
      <div className="qx-empty-title" style={{ color: "inherit" }}>Something went wrong</div>
      <div>{message}</div>
      {onRetry && <button className="qx-btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

/** Confirmation dialog for destructive or irreversible actions. */
export function ConfirmDialog({
  title, message, confirmLabel = "Confirm", cancelLabel = "Cancel", danger = false, busy = false, onConfirm, onCancel,
}: {
  title: string; message: ReactNode; confirmLabel?: string; cancelLabel?: string; danger?: boolean; busy?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <Modal title={title} onClose={onCancel}>
      <div className="qx-confirm-body">{message}</div>
      <div className="qx-modal-actions">
        <button className="qx-btn" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
        <button className={`qx-btn ${danger ? "qx-btn-danger-solid" : "qx-btn-primary"}`} onClick={onConfirm} disabled={busy}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

/**
 * Labelled form control. Wires <label htmlFor>, aria-invalid and
 * aria-describedby onto a single child control (input/select/textarea).
 */
export function FormField({
  label, required, hint, error, children,
}: { label: string; required?: boolean; hint?: ReactNode; error?: string | null; children: ReactNode }) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errId = `${id}-err`;
  const only = Children.count(children) === 1 && isValidElement(children) ? (children as ReactElement<Record<string, unknown>>) : null;
  const control = only
    ? cloneElement(only, {
        id: (only.props.id as string | undefined) ?? id,
        "aria-invalid": error ? true : undefined,
        "aria-required": required ? true : undefined,
        "aria-describedby": [error ? errId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined,
      })
    : children;
  return (
    <div className={`qx-field${error ? " invalid" : ""}`}>
      <label htmlFor={only ? ((only.props.id as string | undefined) ?? id) : undefined}>
        {label}
        {required && <span className="qx-required" aria-hidden="true">*</span>}
      </label>
      {control}
      {hint && <div className="qx-hint" id={hintId}>{hint}</div>}
      {error && <div className="qx-field-error" id={errId} role="alert">{error}</div>}
    </div>
  );
}

export function FoundationNote({ children }: { children: ReactNode }) {
  return <div className="qx-foundation-note">{children}</div>;
}
