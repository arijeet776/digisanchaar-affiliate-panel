import { AppShell } from "../../components/AppShell";
import { ReportsView } from "../../components/ReportsView";

export function ManagerReportsPage() {
  return (
    <AppShell title="Reports">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Reports</div>
          <div className="qx-page-subtitle">
            Performance across your publishers — every figure scoped to your own network and pulled
            from real tracked data.
          </div>
        </div>
      </div>
      <ReportsView
        endpoint="/admin/reports/manager/summary"
        showFinancials
        showManagerFilter={false}
        campaignsUrl="/manager/campaigns"
        groupOptions={[
          { value: "publisher", label: "Publisher" },
          { value: "campaign", label: "Campaign" },
          { value: "event", label: "Event" },
        ]}
      />
    </AppShell>
  );
}
