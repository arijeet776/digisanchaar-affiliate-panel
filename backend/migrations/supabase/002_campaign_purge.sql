-- 002_campaign_purge.sql — run ONCE in Supabase > SQL Editor, AFTER 001_schema.sql.
-- Re-running is safe (create or replace). Nothing here runs by itself.
--
-- qx_purge_campaign(p_campaign_id, p_actor): deletes ONE settled campaign's operational data so the
-- database stays small and fast. Everything happens in ONE transaction: any error rolls it all back.
--
--   HARD DELETED  : clicks, conversions, inbound/outbound postback logs, tracking links, campaign
--                   access, campaign events, attribution mappings, postback endpoints, blocked IPs,
--                   campaign config versions (they carry the campaign name), the campaign row itself.
--   KEPT (B)      : financial_ledger rows — amounts, publisher, direction, dates stay so balances and
--                   payouts still reconcile. Only the campaign link is removed (campaign_id and
--                   conversion_id set to NULL, and name/code keys dropped from metadata).
--   KEPT          : one audit_logs row (action CAMPAIGN_PURGED) with the campaign id and row counts, no name.
--
-- Guard: refuses while any conversion of the campaign is still pending_report (not yet settled).
-- Callable only by the service role (the backend). Never callable from the browser.

create or replace function public.qx_purge_campaign(p_campaign_id text, p_actor text default null)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  t text;
  n int;
  led int := 0;
  pending int;
  counts jsonb := '{}'::jsonb;
  ops_tables text[] := array[
    'inbound_postbacks', 'outbound_postbacks', 'clicks', 'conversions', 'tracking_links',
    'campaign_access', 'blocked_ips', 'postback_endpoints', 'publisher_postback_configs',
    'campaign_config_versions'
  ];
begin
  if p_campaign_id is null or btrim(p_campaign_id) = '' then
    raise exception 'campaign_id is required' using errcode = 'QX001';
  end if;
  if not exists (select 1 from public.campaigns where campaign_id = p_campaign_id) then
    raise exception 'campaign not found' using errcode = 'QX001';
  end if;

  select count(*) into pending from public.conversions
   where campaign_id = p_campaign_id and approval_status = 'pending_report';
  if pending > 0 then
    raise exception 'campaign has % conversion(s) still pending report — settle them first', pending
      using errcode = 'QX001';
  end if;

  -- 1) operational data: hard delete, scoped to this campaign only
  foreach t in array ops_tables loop
    execute format('delete from public.%I where campaign_id = $1', t) using p_campaign_id;
    get diagnostics n = row_count;
    counts := counts || jsonb_build_object(t, n);
  end loop;

  -- 2) financial ledger (append-only): keep the money rows, drop the campaign link only
  alter table public.financial_ledger disable trigger trg_financial_ledger_append_only;
  update public.financial_ledger
     set campaign_id = null,
         conversion_id = null,
         metadata = coalesce(metadata, '{}'::jsonb) - 'campaign_name' - 'campaign_code' - 'campaign_title' - 'advertiser_name'
   where campaign_id = p_campaign_id;
  get diagnostics led = row_count;
  alter table public.financial_ledger enable trigger trg_financial_ledger_append_only;
  counts := counts || jsonb_build_object('financial_ledger_unlinked', led);

  -- 3) the campaign row itself (its name lives here)
  delete from public.campaigns where campaign_id = p_campaign_id;
  get diagnostics n = row_count;
  counts := counts || jsonb_build_object('campaigns', n);

  -- 4) audit: one record, no campaign name
  insert into public.audit_logs (action, actor_user_id, target_user_id, after, metadata, "timestamp")
  values ('CAMPAIGN_PURGED', p_actor, null, null,
          jsonb_build_object('campaign_id', p_campaign_id, 'counts', counts), now());

  return counts;
end $$;

revoke all on function public.qx_purge_campaign(text, text) from public, anon, authenticated;
grant execute on function public.qx_purge_campaign(text, text) to service_role;
