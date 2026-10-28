import { useState } from "react";
import { IconClose, IconPlus } from "../components/Icons";

export interface CampaignEvent {
  event_name: string;
  payout: number;
  completion_source: "online" | "offline";
}

export interface CampaignFormValues {
  name: string;
  advertiser_name: string;
  advertiser_tracking_url: string;
  logo_url: string;
  description: string;
  postback_platform: "trackier" | "offer18" | "custom";
  click_id_param: string;            // advertiser-panel parameter that carries the DigiSNR click id
  advertiser_click_id_param: string; // parameter the advertiser's postback uses for its own click id
  event_param: string;               // parameter carrying the event / goal name
  campaign_title_param: string;      // parameter carrying the campaign title
  extra_click_id_params: string;     // comma separated: more parameters that also carry the DigiSNR click id
  payout_min: string;
  payout_max: string;
  daily_cap: string;
  overall_cap: string;
  approval_mode: "promote_immediately" | "requires_approval";
  category: string;
  kind: "standard" | "shopping" | "survey";
  tracking_only: boolean;
  countries: string; // comma separated
  tracking_window_hours: string; // "" = no validation window (earn at postback)
  events: CampaignEvent[];
}

export const EMPTY_CAMPAIGN_FORM: CampaignFormValues = {
  name: "",
  advertiser_name: "",
  advertiser_tracking_url: "",
  logo_url: "",
  description: "",
  postback_platform: "trackier",
  click_id_param: "p1",
  advertiser_click_id_param: "click_id",
  event_param: "goal_name",
  campaign_title_param: "",
  extra_click_id_params: "",
  payout_min: "",
  payout_max: "",
  daily_cap: "",
  overall_cap: "",
  approval_mode: "promote_immediately",
  category: "",
  kind: "standard",
  tracking_only: false,
  countries: "",
  tracking_window_hours: "",
  events: [{ event_name: "Install", payout: 0, completion_source: "online" }],
};

/** Parameter names each advertiser panel accepts for carrying our click id. Custom is free text. */
const CLICK_ID_CHOICES: Record<CampaignFormValues["postback_platform"], string[]> = {
  trackier: ["p1", "p2", "p3", "p4", "p5", "click_id"],
  offer18: ["aff_sub1", "aff_sub2", "aff_sub3", "aff_sub4", "aff_sub5", "aff_click_id", "sub_aff_id"],
  custom: [],
};

/** Starting values when the panel changes — chosen so the two click-id parameters never collide. */
const PLATFORM_DEFAULTS: Record<CampaignFormValues["postback_platform"], { click: string; adv: string; event: string }> = {
  trackier: { click: "p1", adv: "click_id", event: "goal_name" },
  offer18: { click: "aff_sub1", adv: "aff_click_id", event: "event_token" },
  custom: { click: "", adv: "", event: "" },
};

/** Converts form state (all strings, for controlled inputs) into the JSON body the API expects. */
export function toApiPayload(v: CampaignFormValues) {
  return {
    name: v.name,
    advertiser_name: v.advertiser_name || null,
    advertiser_tracking_url: v.advertiser_tracking_url || null,
    logo_url: v.logo_url || null,
    description: v.description || null,
    platform: v.advertiser_name || null,
    postback_platform: v.postback_platform,
    postback_config: {},
    click_id_param: v.click_id_param.trim() || null,
    advertiser_click_id_param: v.advertiser_click_id_param.trim() || null,
    event_param: v.event_param.trim() || null,
    campaign_title_param: v.campaign_title_param.trim() || null,
    extra_click_id_params: v.extra_click_id_params.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean),
    payout_min: v.payout_min === "" ? null : Number(v.payout_min),
    payout_max: v.payout_max === "" ? null : Number(v.payout_max),
    daily_cap: v.daily_cap === "" ? null : Number(v.daily_cap),
    overall_cap: v.overall_cap === "" ? null : Number(v.overall_cap),
    approval_mode: v.approval_mode,
    category: v.category.trim() || null,
    kind: v.kind,
    tracking_only: v.tracking_only,
    countries: v.countries.split(",").map((c) => c.trim()).filter(Boolean),
    tracking_window_hours: v.tracking_window_hours === "" ? null : Number(v.tracking_window_hours),
    events: v.events,
  };
}

export function CampaignForm({ value, onChange }: { value: CampaignFormValues; onChange: (v: CampaignFormValues) => void }) {
  function set<K extends keyof CampaignFormValues>(key: K, val: CampaignFormValues[K]) {
    onChange({ ...value, [key]: val });
  }

  function updateEvent(index: number, patch: Partial<CampaignEvent>) {
    const events = value.events.map((ev, i) => (i === index ? { ...ev, ...patch } : ev));
    set("events", events);
  }

  function addEvent() {
    set("events", [...value.events, { event_name: "", payout: 0, completion_source: "online" }]);
  }

  function removeEvent(index: number) {
    set("events", value.events.filter((_, i) => i !== index));
  }

  return (
    <>
      <div className="qx-section-title" style={{ marginTop: 0 }}>Basics</div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-name">Campaign name</label>
          <input id="c-name" className="qx-input" value={value.name} onChange={(e) => set("name", e.target.value)} required />
        </div>
        <div className="qx-field">
          <label htmlFor="c-advertiser">Advertiser / Company</label>
          <input id="c-advertiser" className="qx-input" value={value.advertiser_name} onChange={(e) => set("advertiser_name", e.target.value)} />
        </div>
      </div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-tracking-url">Advertiser tracking URL</label>
          <input id="c-tracking-url" className="qx-input" value={value.advertiser_tracking_url} onChange={(e) => set("advertiser_tracking_url", e.target.value)} />
        </div>
        <div className="qx-field">
          <label htmlFor="c-logo">Logo URL</label>
          <input id="c-logo" className="qx-input" value={value.logo_url} onChange={(e) => set("logo_url", e.target.value)} />
          <div className="qx-hint">Binary upload isn't available yet (no storage service integrated) — paste a hosted image URL.</div>
        </div>
      </div>
      <div className="qx-field">
        <label htmlFor="c-desc">Description / Instructions</label>
        <textarea id="c-desc" className="qx-textarea" value={value.description} onChange={(e) => set("description", e.target.value)} />
      </div>
      <div className="qx-section-title">Postback &amp; Click ID</div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-pb-platform">Advertiser panel</label>
          <select id="c-pb-platform" className="qx-select" value={value.postback_platform}
            onChange={(e) => {
              const p = e.target.value as CampaignFormValues["postback_platform"];
              const d = PLATFORM_DEFAULTS[p];
              onChange({ ...value, postback_platform: p, click_id_param: d.click, advertiser_click_id_param: d.adv, event_param: d.event });
            }}>
            <option value="trackier">Trackier</option>
            <option value="offer18">Offer18</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        <div className="qx-field">
          <label htmlFor="c-pb-clickparam">DigiSNR click id goes in parameter</label>
          {CLICK_ID_CHOICES[value.postback_platform].length > 0 ? (
            <select id="c-pb-clickparam" className="qx-select" value={value.click_id_param} onChange={(e) => set("click_id_param", e.target.value)}>
              {CLICK_ID_CHOICES[value.postback_platform].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          ) : (
            <input id="c-pb-clickparam" className="qx-input" placeholder="e.g. sub1" value={value.click_id_param} onChange={(e) => set("click_id_param", e.target.value)} />
          )}
          <div className="qx-hint">Every click is sent to the advertiser with our id in this parameter, and the postback brings it back through the same one. Publishers cannot use it.</div>
        </div>
      </div>
      <div className="qx-field">
        <label htmlFor="c-pb-extraparams">Also send the same DigiSNR click id in (optional)</label>
        <input id="c-pb-extraparams" className="qx-input" placeholder="e.g. source" value={value.extra_click_id_params} onChange={(e) => set("extra_click_id_params", e.target.value)} />
        <div className="qx-hint">For advertisers that want our click id in two parameters, e.g. p1 and source. Separate several with commas. Each one is added to the advertiser link with the same DigiSNR click id.</div>
      </div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-pb-advparam">Advertiser click id parameter</label>
          <input id="c-pb-advparam" className="qx-input" placeholder="e.g. click_id" value={value.advertiser_click_id_param} onChange={(e) => set("advertiser_click_id_param", e.target.value)} />
        </div>
        <div className="qx-field">
          <label htmlFor="c-pb-eventparam">Event / goal parameter</label>
          <input id="c-pb-eventparam" className="qx-input" placeholder="e.g. goal_name, event, goal_title" value={value.event_param} onChange={(e) => set("event_param", e.target.value)} />
        </div>
      </div>
      <div className="qx-field">
        <label htmlFor="c-pb-titleparam">Campaign title parameter (optional)</label>
        <input id="c-pb-titleparam" className="qx-input" placeholder="e.g. campaign_title, camp_name" value={value.campaign_title_param} onChange={(e) => set("campaign_title_param", e.target.value)} />
      </div>

      <div className="qx-section-title">Payout &amp; Caps</div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-payout-min">Payout min</label>
          <input id="c-payout-min" className="qx-input" type="number" min={0} value={value.payout_min} onChange={(e) => set("payout_min", e.target.value)} />
        </div>
        <div className="qx-field">
          <label htmlFor="c-payout-max">Payout max</label>
          <input id="c-payout-max" className="qx-input" type="number" min={0} value={value.payout_max} onChange={(e) => set("payout_max", e.target.value)} />
        </div>
      </div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-daily-cap">Daily cap (blank = unlimited)</label>
          <input id="c-daily-cap" className="qx-input" type="number" min={0} value={value.daily_cap} onChange={(e) => set("daily_cap", e.target.value)} />
        </div>
        <div className="qx-field">
          <label htmlFor="c-overall-cap">Overall / lifetime cap (blank = unlimited)</label>
          <input id="c-overall-cap" className="qx-input" type="number" min={0} value={value.overall_cap} onChange={(e) => set("overall_cap", e.target.value)} />
        </div>
      </div>

      <div className="qx-section-title">Access &amp; Validation</div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-approval">Publisher access</label>
          <select id="c-approval" className="qx-select" value={value.approval_mode} onChange={(e) => set("approval_mode", e.target.value as CampaignFormValues["approval_mode"])}>
            <option value="promote_immediately">Promote immediately — no approval needed</option>
            <option value="requires_approval">Requires approval — manager/admin approves each publisher</option>
          </select>
        </div>
        <div className="qx-field">
          <label htmlFor="c-window">Tracking / validation time</label>
          <select id="c-window" className="qx-select" value={["", "24", "48", "72", "168", "360"].includes(value.tracking_window_hours) ? value.tracking_window_hours : "custom"} onChange={(e) => set("tracking_window_hours", e.target.value === "custom" ? "1" : e.target.value)}>
            <option value="">None — earn when the postback arrives</option>
            <option value="24">24 hours</option>
            <option value="48">48 hours</option>
            <option value="72">72 hours</option>
            <option value="168">7 days</option>
            <option value="360">15 days</option>
            <option value="custom">Custom (hours)…</option>
          </select>
          {!["", "24", "48", "72", "168", "360"].includes(value.tracking_window_hours) && (
            <input className="qx-input" style={{ marginTop: 6 }} type="number" min={1} value={value.tracking_window_hours} onChange={(e) => set("tracking_window_hours", e.target.value)} aria-label="Custom validation hours" />
          )}
          <div className="qx-hint">With a window set, conversions stay pending until the company's report is recorded; the publisher is only credited when it is confirmed.</div>
        </div>
      </div>

      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-category">Category</label>
          <input id="c-category" className="qx-input" placeholder="e.g. Finance" value={value.category} onChange={(e) => set("category", e.target.value)} />
        </div>
        <div className="qx-field">
          <label htmlFor="c-kind">Kind</label>
          <select id="c-kind" className="qx-select" value={value.kind} onChange={(e) => set("kind", e.target.value as CampaignFormValues["kind"])}>
            <option value="standard">Standard</option><option value="shopping">Shopping</option><option value="survey">Survey</option>
          </select>
        </div>
      </div>
      <div className="qx-row">
        <div className="qx-field">
          <label htmlFor="c-countries">Countries (comma separated)</label>
          <input id="c-countries" className="qx-input" placeholder="India, UAE" value={value.countries} onChange={(e) => set("countries", e.target.value)} />
        </div>
        <div className="qx-field">
          <label htmlFor="c-trackonly">Tracking only</label>
          <select id="c-trackonly" className="qx-select" value={value.tracking_only ? "yes" : "no"} onChange={(e) => set("tracking_only", e.target.value === "yes")}>
            <option value="no">No</option><option value="yes">Yes — show "Tracking Only" label</option>
          </select>
        </div>
      </div>

      <div className="qx-section-title">Events</div>
      {value.events.map((ev, i) => (
        <div key={i} className="qx-row" style={{ alignItems: "end", marginBottom: 8 }}>
          <div className="qx-field" style={{ marginBottom: 0 }}>
            <label>Event name</label>
            <input className="qx-input" value={ev.event_name} onChange={(e) => updateEvent(i, { event_name: e.target.value })} />
          </div>
          <div className="qx-field" style={{ marginBottom: 0 }}>
            <label>Payout (₹0 is valid)</label>
            <input className="qx-input" type="number" min={0} value={ev.payout} onChange={(e) => updateEvent(i, { payout: Number(e.target.value) })} />
          </div>
          <div className="qx-field" style={{ marginBottom: 0, display: "flex", gap: 8, alignItems: "flex-end" }}>
            <div style={{ flex: 1 }}>
              <label>Completion source</label>
              <select className="qx-select" value={ev.completion_source} onChange={(e) => updateEvent(i, { completion_source: e.target.value as "online" | "offline" })}>
                <option value="online">Online</option>
                <option value="offline">Offline</option>
              </select>
            </div>
            <button type="button" className="qx-icon-btn" onClick={() => removeEvent(i)} aria-label="Remove event">
              <IconClose width={14} height={14} />
            </button>
          </div>
        </div>
      ))}
      <button type="button" className="qx-btn qx-btn-sm" onClick={addEvent}>
        <IconPlus width={13} height={13} /> Add event
      </button>
    </>
  );
}

export function useCampaignForm(initial: CampaignFormValues = EMPTY_CAMPAIGN_FORM) {
  return useState<CampaignFormValues>(initial);
}
