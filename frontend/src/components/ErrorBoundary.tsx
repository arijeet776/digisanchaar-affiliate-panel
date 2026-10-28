import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { error: Error | null }

/** Prevents a render-time exception from leaving a blank white screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI error", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" data-testid="error-boundary" style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", flexDirection: "column", gap: 10, padding: 16, textAlign: "center" }}>
        <div style={{ fontSize: 18, fontWeight: 700 }}>Something went wrong</div>
        <div style={{ color: "var(--text-secondary)", fontSize: 13 }}>The page failed to load. Please reload; if it keeps happening, sign in again.</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="qx-btn qx-btn-primary" onClick={() => window.location.reload()}>Reload</button>
          <a className="qx-btn qx-btn-primary" href="/login">Go to login</a>
        </div>
      </div>
    );
  }
}
