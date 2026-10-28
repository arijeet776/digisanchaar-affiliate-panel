import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import { AppShell } from "../../components/AppShell";
import { CampaignTable, type CampaignRow } from "../../components/CampaignTable";
import { EmptyState, ErrorBanner } from "../../components/Common";
import { IconSearch } from "../../components/Icons";

interface Approved extends CampaignRow { events: { event_name: string; payout: number }[] }

export function PublisherCampaignsPage() {
  const [items, setItems] = useState<Approved[] | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<Approved[]>("/publisher/campaigns")
      .then((r) => setItems(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load campaigns"));
  }, []);

  const q = search.trim().toLowerCase();
  const rows = (items ?? []).filter((c) => !q || c.name.toLowerCase().includes(q) || c.campaign_id.includes(q));

  return (
    <AppShell title="Campaigns">
      <div className="qx-page-header">
        <div><div className="qx-page-title">Approved Offers</div></div>
      </div>
      <ErrorBanner message={error} />
      <div className="qx-filter-card">
        <div className="qx-search">
          <IconSearch width={18} height={18} />
          <input className="qx-input" placeholder="Search approved campaigns by name or ID…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search approved campaigns" />
        </div>
      </div>
      {!items ? <div className="qx-empty-state">Loading…</div> : rows.length === 0 ? (
        <div data-testid="publisher-campaigns-empty"><EmptyState message="No approved campaigns yet. Open All Campaigns to start promoting." /></div>
      ) : (
        <div data-testid="publisher-campaigns-list">
          <CampaignTable rows={rows} extraHead={["Top Payout"]}
            extraCell={(r) => [`₹${Math.max(0, ...(r as Approved).events.map((e) => e.payout))}`]} />
        </div>
      )}
    </AppShell>
  );
}
