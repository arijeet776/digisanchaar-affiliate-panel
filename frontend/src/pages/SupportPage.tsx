import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { api, ApiError } from "../api/client";
import { AppShell } from "../components/AppShell";
import { EmptyState, ErrorBanner, Modal, Pagination, StatusBadge } from "../components/Common";

interface TicketMessage {
  author_user_id: string;
  author_role: string;
  body: string;
  created_at: string;
}

interface Ticket {
  ticket_id: string;
  subject: string;
  category: string;
  priority: string;
  status: string;
  created_by_user_id: string;
  created_by_role: string;
  publisher_id: string | null;
  manager_id: string | null;
  messages: TicketMessage[];
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  closed_at: string | null;
}

const PAGE_SIZE = 20;
const CATEGORIES = [
  { value: "account", label: "Account" },
  { value: "campaign", label: "Campaign" },
  { value: "tracking", label: "Tracking" },
  { value: "postback", label: "Postback" },
  { value: "payments", label: "Payments" },
  { value: "other", label: "Other" },
];
const PRIORITIES = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
];

interface Contact { manager: { name: string; mobile: string | null } | null; whatsapp_group_link: string | null }

/** Real contact data: assigned Manager (name + mobile) and the Super Admin
 * configured WhatsApp group. Nothing hardcoded; absent values get an empty state. */
function ContactCard({ role }: { role: string | undefined }) {
  const [c, setC] = useState<Contact | null>(null);
  useEffect(() => { api.get<Contact>("/support/contact").then((r) => setC(r.data)).catch(() => setC({ manager: null, whatsapp_group_link: null })); }, []);
  if (!c) return null;
  const isPub = role === "publisher";
  return (
    <div className="qx-card qx-contact-card" data-testid="support-contact" style={{ marginBottom: 16 }}>
      {isPub && (
        <div className="qx-contact-row" data-testid="support-manager">
          <div className="qx-stat-label">Assigned Manager</div>
          {c.manager ? (
            <>
              <div style={{ fontWeight: 700 }} data-testid="support-manager-name">{c.manager.name}</div>
              <div className="qx-hint" data-testid="support-manager-mobile">
                {c.manager.mobile ? <a href={`tel:${c.manager.mobile.replace(/\s+/g, "")}`}>{c.manager.mobile}</a> : "Mobile number not provided yet"}
              </div>
            </>
          ) : <div className="qx-hint" data-testid="support-manager-empty">Manager not assigned yet</div>}
        </div>
      )}
      <div className="qx-contact-row">
        {c.whatsapp_group_link ? (
          <a className="qx-btn qx-btn-primary" href={c.whatsapp_group_link} target="_blank" rel="noopener noreferrer" data-testid="support-whatsapp">
            Join DigiSanchaar WhatsApp Group
          </a>
        ) : (
          <>
            <button className="qx-btn" disabled aria-disabled="true" data-testid="support-whatsapp-disabled">Join DigiSanchaar WhatsApp Group</button>
            <div className="qx-hint" style={{ marginTop: 6 }}>The WhatsApp group isn't available yet.</div>
          </>
        )}
      </div>
    </div>
  );
}

export function SupportPage() {
  const { user } = useAuth();
  const canManage = user?.role === "manager" || user?.role === "super_admin";

  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<Ticket[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [selected, setSelected] = useState<Ticket | null>(null);

  function load() {
    api
      .get<{ items: Ticket[]; total: number }>("/support/tickets", { status: status || undefined, page, page_size: PAGE_SIZE })
      .then((r) => {
        setRows(r.data.items);
        setTotal(r.data.total);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load support tickets"));
  }

  useEffect(load, [status, page]);

  function openTicket(ticketId: string) {
    api
      .get<Ticket>(`/support/tickets/${ticketId}`)
      .then((r) => setSelected(r.data))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load ticket"));
  }

  return (
    <AppShell title="Support & Help">
      <div className="qx-page-header">
        <div>
          <div className="qx-page-title">Support & Help</div>
          <div className="qx-page-subtitle">
            {canManage
              ? "Tickets raised by your publishers and your own requests."
              : "Raise a ticket for anything you need help with — a manager or admin will respond here."}
          </div>
        </div>
        <button className="qx-btn qx-btn-primary" onClick={() => setCreateOpen(true)}>
          New Ticket
        </button>
      </div>

      <ContactCard role={user?.role} />

      <ErrorBanner message={error} />

      <div className="qx-row" style={{ marginBottom: 14, maxWidth: 260 }}>
        <select
          className="qx-select"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="in_progress">In progress</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="No support tickets yet." />
      ) : (
        <div className="qx-table-wrap">
          <table className="qx-table">
            <thead>
              <tr>
                <th>Subject</th>
                <th>Category</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.ticket_id} onClick={() => openTicket(t.ticket_id)} style={{ cursor: "pointer" }} data-testid={`ticket-row-${t.ticket_id}`}>
                  <td>{t.subject}</td>
                  <td style={{ textTransform: "capitalize" }}>{t.category}</td>
                  <td style={{ textTransform: "capitalize" }}>{t.priority}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td>{new Date(t.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />

      {createOpen && (
        <CreateTicketModal
          onClose={() => setCreateOpen(false)}
          onSuccess={() => {
            setCreateOpen(false);
            load();
          }}
        />
      )}

      {selected && (
        <TicketDetailModal
          ticket={selected}
          canManage={canManage}
          currentUserId={user?.user_id ?? ""}
          onClose={() => setSelected(null)}
          onUpdated={(t) => {
            setSelected(t);
            load();
          }}
        />
      )}
    </AppShell>
  );
}

function CreateTicketModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("other");
  const [priority, setPriority] = useState("normal");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const valid = subject.trim().length >= 3 && message.trim().length >= 3;

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/support/tickets", { subject, category, priority, message });
      onSuccess();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create ticket");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="New Support Ticket" onClose={onClose}>
      <ErrorBanner message={error} />
      <div className="qx-field">
        <label htmlFor="ticket-subject">Subject</label>
        <input id="ticket-subject" className="qx-input" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Short summary of the issue" />
      </div>
      <div className="qx-row" style={{ gap: 10 }}>
        <div className="qx-field" style={{ flex: 1 }}>
          <label htmlFor="ticket-category">Category</label>
          <select id="ticket-category" className="qx-select" value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
        <div className="qx-field" style={{ flex: 1 }}>
          <label htmlFor="ticket-priority">Priority</label>
          <select id="ticket-priority" className="qx-select" value={priority} onChange={(e) => setPriority(e.target.value)}>
            {PRIORITIES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="qx-field">
        <label htmlFor="ticket-message">Message</label>
        <textarea id="ticket-message" className="qx-textarea" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Describe what's happening…" />
      </div>
      <button className="qx-btn qx-btn-primary" disabled={!valid || submitting} onClick={submit}>
        {submitting ? "Submitting…" : "Submit Ticket"}
      </button>
    </Modal>
  );
}

function TicketDetailModal({
  ticket,
  canManage,
  currentUserId,
  onClose,
  onUpdated,
}: {
  ticket: Ticket;
  canManage: boolean;
  currentUserId: string;
  onClose: () => void;
  onUpdated: (t: Ticket) => void;
}) {
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Mirrors the server-side transition map in support_service.py — purely a
  // UX convenience so the dropdown doesn't offer choices the server will
  // reject with 409; the server remains the authority on what's actually valid.
  const NEXT_STATUSES: Record<string, string[]> = {
    open: ["in_progress", "resolved", "closed"],
    in_progress: ["open", "resolved", "closed"],
    resolved: ["in_progress", "closed"],
    closed: [],
  };
  const STATUS_LABELS: Record<string, string> = {
    open: "Open",
    in_progress: "In progress",
    resolved: "Resolved",
    closed: "Closed",
  };

  async function sendReply() {
    if (!reply.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await api.post<Ticket>(`/support/tickets/${ticket.ticket_id}/reply`, { body: reply });
      setReply("");
      onUpdated(r.data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not send reply");
    } finally {
      setSubmitting(false);
    }
  }

  async function changeStatus(newStatus: string) {
    setError(null);
    try {
      const r = await api.post<Ticket>(`/support/tickets/${ticket.ticket_id}/status`, { status: newStatus });
      onUpdated(r.data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update status");
    }
  }

  return (
    <Modal title={ticket.subject} onClose={onClose}>
      <ErrorBanner message={error} />
      <div className="qx-row" style={{ marginBottom: 10, gap: 8, alignItems: "center" }}>
        <StatusBadge status={ticket.status} />
        <span style={{ color: "var(--text-secondary)", fontSize: 12.5, textTransform: "capitalize" }}>{ticket.category} · {ticket.priority} priority</span>
        {canManage && ticket.status !== "closed" && (
          <select className="qx-select" style={{ marginLeft: "auto" }} value={ticket.status} onChange={(e) => changeStatus(e.target.value)}>
            <option value={ticket.status} disabled>{STATUS_LABELS[ticket.status]} (current)</option>
            {NEXT_STATUSES[ticket.status]?.map((s) => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </select>
        )}
      </div>

      <div style={{ maxHeight: 320, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10, marginBottom: 12 }}>
        {ticket.messages.map((m, i) => {
          const mine = m.author_user_id === currentUserId;
          return (
            <div
              key={i}
              style={{
                alignSelf: mine ? "flex-end" : "flex-start",
                maxWidth: "85%",
                background: mine ? "var(--accent-soft)" : "var(--surface-hover)",
                border: "1px solid var(--border-strong)",
                borderRadius: 10,
                padding: "8px 11px",
              }}
            >
              <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 3, textTransform: "capitalize" }}>
                {m.author_role.replace(/_/g, " ")} · {new Date(m.created_at).toLocaleString()}
              </div>
              <div style={{ fontSize: 13.5, whiteSpace: "pre-wrap" }}>{m.body}</div>
            </div>
          );
        })}
      </div>

      {ticket.status !== "closed" && (
        <div className="qx-field">
          <label htmlFor="ticket-reply">Reply</label>
          <textarea id="ticket-reply" className="qx-textarea" value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Write a reply…" />
          <button className="qx-btn qx-btn-primary" style={{ marginTop: 8 }} disabled={!reply.trim() || submitting} onClick={sendReply}>
            {submitting ? "Sending…" : "Send Reply"}
          </button>
        </div>
      )}
    </Modal>
  );
}
