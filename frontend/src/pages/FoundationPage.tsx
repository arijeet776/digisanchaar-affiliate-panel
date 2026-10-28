import type { ReactNode } from "react";
import { AppShell } from "../components/AppShell";
import { FoundationNote } from "../components/Common";

export function FoundationPage({
  title,
  subtitle,
  note,
  children,
}: {
  title: string;
  subtitle: string;
  note: ReactNode;
  children?: ReactNode;
}) {
  return (
    <AppShell title={title}>
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">{title}</div>
          <div className="qx-page-subtitle">{subtitle}</div>
        </div>
      </div>
      <FoundationNote>{note}</FoundationNote>
      {children}
    </AppShell>
  );
}
