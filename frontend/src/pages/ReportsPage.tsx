import { AppShell } from "../components/AppShell";
import { ReportsView } from "../components/ReportsView";

export function ReportsPage() {
  return (
    <AppShell title="Reports">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Reports</div>
          <div className="qx-page-subtitle">
            Network performance — clicks, conversions, revenue, payout and margin, from real tracked
            records only.
          </div>
        </div>
      </div>
      <ReportsView
        endpoint="/admin/reports/summary"
        exportUrl="/admin/reports/export.csv"
        showFinancials
        showManagerFilter
        campaignsUrl="/admin/campaigns"
        groupOptions={[
          { value: "campaign", label: "Campaign" },
          { value: "manager", label: "Manager" },
          { value: "publisher", label: "Publisher" },
          { value: "event", label: "Event" },
        ]}
      />
    </AppShell>
  );
}
