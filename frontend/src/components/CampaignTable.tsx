import { useNavigate } from "react-router-dom";
import type { ReactNode } from "react";

export interface CampaignRow {
  campaign_id: string;
  name: string;
  logo_url?: string | null;
  tracking_only?: boolean;
  status?: string;
}

export function CampaignTable({ rows, extraHead, extraCell }: {
  rows: CampaignRow[];
  extraHead?: string[];
  extraCell?: (r: CampaignRow) => ReactNode[];
}) {
  const navigate = useNavigate();
  return (
    <div className="qx-grad-table">
      <table>
        <thead>
          <tr><th>ID</th><th>Campaign Name</th>{extraHead?.map((h) => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.campaign_id} onClick={() => navigate(`/publisher/campaigns/${r.campaign_id}`)} data-testid={`campaign-row-${r.campaign_id}`}>
              <td className="qx-cid">#{r.campaign_id}</td>
              <td>
                <div className="qx-cell-campaign">
                  {r.logo_url ? <img className="qx-clogo" src={r.logo_url} alt="" /> : <div className="qx-clogo">{r.name.slice(0, 1)}</div>}
                  <div>
                    <div className="qx-cname">{r.name} <span className="qx-active-pill">{(r.status ?? "active").toUpperCase()}</span></div>
                    {r.tracking_only && <div className="qx-csub">Tracking Only</div>}
                  </div>
                </div>
              </td>
              {extraCell?.(r).map((c, i) => <td key={i}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
