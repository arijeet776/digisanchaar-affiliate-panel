import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { ErrorBanner, Modal, StatusBadge } from "../components/Common";
import { SuccessPopup } from "../components/SuccessPopup";

interface TrackingLink {
  link_id: string;
  public_code: string;
  campaign_id: string;
  campaign_code: string;
  campaign_name: string | null;
  publisher_id: string;
  publisher_code: string;
  publisher_name: string | null;
  manager_id: string;
  status: string;
  tracking_url: string | null;
  click_count: number;
  created_at: string;
}

interface CampaignOption {
  campaign_id: string;
  name: string;
}

interface PublisherOption {
  publisher_id: string;
  display_name: string;
  email: string;
  account_status: string;
}

export function TrackingLinksPage() {
  const [links, setLinks] = useState<TrackingLink[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  function load() {
    api
      .get<TrackingLink[]>("/links")
      .then((r) => setLinks(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load tracking links"));
  }

  useEffect(load, []);

  return (
    <AppShell title="Tracking Links">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Tracking Links</div>
          <div className="qx-page-subtitle">
            Short public links — {"{tracking-domain}/{campaign-code}/{link-code}"} — resolved server-side to the
            correct campaign and publisher.
          </div>
        </div>
        <button className="qx-btn qx-btn-primary" onClick={() => setGenerateOpen(true)} data-testid="generate-link-button">
          + Generate Link
        </button>
      </div>

      <ErrorBanner message={error} />

      {!links ? (
        <div className="qx-empty-state">Loading…</div>
      ) : links.length === 0 ? (
        <div className="qx-empty-state" data-testid="links-empty">
          No tracking links yet. Generate one for an active campaign and an active publisher. The
          tracking domain must be configured under System Settings → Domain &amp; Tracking first.
        </div>
      ) : (
        <div className="qx-table-wrap" data-testid="links-table">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Tracking URL</th>
                <th>Campaign</th>
                <th>Publisher</th>
                <th>Manager</th>
                <th>Clicks</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {links.map((l) => (
                <tr key={l.link_id}>
                  <td>
                    <code data-testid={`tracking-url-${l.link_id}`}>{l.tracking_url ?? `${l.campaign_code}/${l.public_code}`}</code>
                  </td>
                  <td>
                    <Link to={`/campaigns/${l.campaign_id}`}>{l.campaign_name ?? l.campaign_id}</Link>
                  </td>
                  <td>{l.publisher_name ? `${l.publisher_name} (${l.publisher_id})` : l.publisher_id}</td>
                  <td>{l.manager_id}</td>
                  <td className="qx-amount">{l.click_count}</td>
                  <td><StatusBadge status={l.status} /></td>
                  <td>
                    {l.tracking_url && (
                      <button
                        className="qx-btn qx-btn-sm"
                        data-testid={`copy-link-${l.link_id}`}
                        onClick={async () => {
                          await navigator.clipboard.writeText(l.tracking_url!);
                          setCopiedId(l.link_id);
                          setTimeout(() => setCopiedId(null), 1500);
                        }}
                      >
                        {copiedId === l.link_id ? "Copied ✓" : "Copy"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {generateOpen && (
        <GenerateLinkModal
          onClose={() => setGenerateOpen(false)}
          onCreated={() => {
            setGenerateOpen(false);
            load();
          }}
        />
      )}
    </AppShell>
  );
}

function GenerateLinkModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [campaigns, setCampaigns] = useState<CampaignOption[]>([]);
  const [publishers, setPublishers] = useState<PublisherOption[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [publisherId, setPublisherId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<TrackingLink | null>(null);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api
      .get<CampaignOption[]>("/admin/campaigns", { status: "active", page_size: 100 })
      .then((r) => setCampaigns(r.data))
      .catch(() => setCampaigns([]));
    api
      .get<PublisherOption[]>("/publishers", { status: "active", page_size: 200 })
      .then((r) => setPublishers(r.data))
      .catch(() => setPublishers([]));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<TrackingLink>("/links", { campaign_id: campaignId, publisher_id: publisherId });
      setCreated(r.data); setNoticeOpen(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to generate link");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Generate Tracking Link" onClose={onClose}>
      <ErrorBanner message={error} />
      {!created ? (
        <form onSubmit={submit}>
          <div className="qx-field">
            <label htmlFor="link-campaign">Campaign (active only)</label>
            <select
              id="link-campaign"
              className="qx-select"
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
              required
              data-testid="link-campaign-select"
            >
              <option value="">Select campaign…</option>
              {campaigns.map((c) => (
                <option key={c.campaign_id} value={c.campaign_id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div className="qx-field">
            <label htmlFor="link-publisher">Publisher (active only)</label>
            <select
              id="link-publisher"
              className="qx-select"
              value={publisherId}
              onChange={(e) => setPublisherId(e.target.value)}
              required
              data-testid="link-publisher-select"
            >
              <option value="">Select publisher…</option>
              {publishers.map((p) => (
                <option key={p.publisher_id} value={p.publisher_id}>
                  {p.display_name} ({p.publisher_id})
                </option>
              ))}
            </select>
          </div>
          <div className="qx-hint" style={{ marginBottom: 12 }}>
            One active link per campaign + publisher. The URL is built from the configured tracking
            domain — internal IDs are never exposed in it.
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="qx-btn" type="button" onClick={onClose}>Cancel</button>
            <button className="qx-btn qx-btn-primary" disabled={busy || !campaignId || !publisherId} type="submit" data-testid="link-create-submit">
              {busy ? "Generating…" : "Generate Link"}
            </button>
          </div>
        </form>
      ) : (
        <div data-testid="link-created">
          <SuccessPopup open={noticeOpen} onClose={() => setNoticeOpen(false)} title="Tracking link ready">
            For {created.publisher_name ?? created.publisher_id}.
          </SuccessPopup>
          <div className="qx-field">
            <label>Public tracking URL</label>
            <code className="qx-code" data-testid="created-tracking-url">{created.tracking_url}</code>
            <div className="qx-hint">
              The publisher can append ?p1=…&p10=… and UTM parameters — they are captured with every
              click and returned in their postback exactly as sent.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              className="qx-btn qx-btn-primary"
              data-testid="created-copy-button"
              onClick={async () => {
                if (created.tracking_url) {
                  await navigator.clipboard.writeText(created.tracking_url);
                  setCopied(true);
                }
              }}
            >
              {copied ? "Copied ✓" : "Copy URL"}
            </button>
            <button className="qx-btn" onClick={onCreated} data-testid="created-done-button">Done</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
