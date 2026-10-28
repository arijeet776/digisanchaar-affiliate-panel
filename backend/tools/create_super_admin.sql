-- ONE-TIME first Super Admin for Supabase. Run in Supabase > SQL Editor.
-- The password is typed ONLY here (replace the two <...> placeholders); it is hashed inside the database
-- (bcrypt, same format the app verifies at login). It is never sent to the frontend, never stored in plain text,
-- never put in code, git, chat or a ZIP. After running: delete this tab's text so the password is not kept in query history.
-- Refuses (does nothing) if the email already exists or an active super_admin already exists.
create extension if not exists pgcrypto with schema extensions;

with params as (
  select lower(trim('<ADMIN_EMAIL>')) as email, '<STRONG_PASSWORD>'::text as pw
), guard as (
  select p.* from params p
  where length(p.pw) >= 12 and p.pw ~ '[a-z]' and p.pw ~ '[A-Z]' and p.pw ~ '[0-9]' and p.email like '%@%'
    and not exists (select 1 from public.users u where u.email = p.email)
    and not exists (select 1 from public.users u where u.role = 'super_admin' and u.account_status = 'active')
), ins as (
  insert into public.users (email, role, account_status, email_verified, password_hash, created_at, updated_at)
  select email, 'super_admin', 'active', true, extensions.crypt(pw, extensions.gen_salt('bf', 12)), now(), now() from guard
  returning "_id", email
), aud as (
  insert into public.audit_logs (action, actor_user_id, target_user_id, after, metadata, "timestamp")
  select 'SUPER_ADMIN_BOOTSTRAPPED', null, "_id", '{"role":"super_admin","account_status":"active"}'::jsonb, '{"via":"sql_editor"}'::jsonb, now() from ins
  returning 1
)
select case when exists (select 1 from ins) then 'CREATED: ' || (select email from ins)
            else 'REFUSED: weak password (needs 12+ chars with upper, lower, digit), invalid email, email already exists, or an active super_admin already exists' end as result;
