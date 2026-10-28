-- ============================================================================
-- DigiSanchaar storage engine for Supabase (PostgREST RPC).
-- ONE entry point:  select qx_exec('{"action":"query","table":"users",...}'::jsonb)
-- It speaks the same wire protocol as the Python storage adapter, so the Python adapter and the
-- Mongo-style filters/updates used by the repositories keep working unchanged,
-- but every request is ONE round trip and ONE transaction (batch = atomic).
-- Dynamic SQL uses %I / %L only; table names must exist in qx_tables; field
-- paths are validated against ^[A-Za-z0-9_.]+$ - there is no string splicing of
-- caller input.
-- ============================================================================

create or replace function qx_oid() returns text language sql volatile as
$$ select substr(replace(gen_random_uuid()::text, '-', ''), 1, 24) $$;

create or replace function qx_fail(p_code text, p_message text) returns void language plpgsql as $$
begin
  raise exception using errcode = 'QX001', message = jsonb_build_object('code', p_code, 'message', p_message)::text;
end $$;

create or replace function qx_pgtype(c text) returns text language sql immutable as $$
  select case c when 's' then 'text' when 'i' then 'bigint' when 'f' then 'double precision' when 'b' then 'boolean'
                when 'd' then 'timestamptz' when 'm' then 'numeric(18,2)' when 'j' then 'jsonb' else 'text' end $$;

create or replace function qx_tbl(p_t text) returns qx_tables language plpgsql stable as $$
declare v qx_tables;
begin
  select * into v from qx_tables where collection = p_t;
  if not found then perform qx_fail('INVALID_TABLE', 'Unknown table'); end if;
  return v;
end $$;

-- field path -> SQL expression (alias r) + its Postgres type
create or replace function qx_field(p_t text, p_path text, out expr text, out typ text) language plpgsql stable as $$
declare v_types jsonb; v_base text; v_sub text;
begin
  if p_path is null or p_path !~ '^[A-Za-z0-9_.]+$' then perform qx_fail('VALIDATION_ERROR', 'Invalid field name'); end if;
  select coltypes into v_types from qx_tables where collection = p_t;
  v_base := split_part(p_path, '.', 1);
  if v_types ? v_base then
    if position('.' in p_path) = 0 then
      expr := format('r.%I', v_base); typ := qx_pgtype(v_types ->> v_base);
    else
      v_sub := '{' || replace(substr(p_path, length(v_base) + 2), '.', ',') || '}';
      expr := format('(r.%I #>> %L)', v_base, v_sub); typ := 'text';
    end if;
  else
    expr := format('(r._extra #>> %L)', '{' || replace(p_path, '.', ',') || '}'); typ := 'text';
  end if;
end $$;

create or replace function qx_lit(v jsonb, typ text) returns text language plpgsql immutable as $$
begin
  if v is null or jsonb_typeof(v) = 'null' then return 'null'; end if;
  if typ = 'jsonb' then return format('%L::jsonb', v::text); end if;
  if jsonb_typeof(v) in ('object', 'array') then perform qx_fail('VALIDATION_ERROR', 'Unsupported comparison value'); end if;
  return format('%L::%s', v #>> '{}', typ);
end $$;

create or replace function qx_cond(p_expr text, p_typ text, c jsonb, depth int) returns text language plpgsql stable as $$
declare op text; arg jsonb; parts text[] := '{}'; lst text; has_null boolean; el jsonb; opts text;
begin
  if depth > 8 then perform qx_fail('VALIDATION_ERROR', 'Filter too deeply nested'); end if;
  if c is null or jsonb_typeof(c) = 'null' then return format('(%s is null)', p_expr); end if;
  if jsonb_typeof(c) <> 'object' or not exists (select 1 from jsonb_object_keys(c) k where left(k, 1) = '$') then
    if jsonb_typeof(c) = 'object' or jsonb_typeof(c) = 'array' then
      return format('(%s::text = %L)', p_expr, c::text);
    end if;
    return format('(%s = %s)', p_expr, qx_lit(c, p_typ));
  end if;
  opts := coalesce(c ->> '$options', '');
  for op, arg in select * from jsonb_each(c) loop
    if op = '$eq' then parts := parts || format('(%s is not distinct from %s)', p_expr, qx_lit(arg, p_typ));
    elsif op = '$ne' then parts := parts || format('(%s is distinct from %s)', p_expr, qx_lit(arg, p_typ));
    elsif op in ('$gt', '$gte', '$lt', '$lte') then
      parts := parts || format('(%s %s %s)', p_expr, case op when '$gt' then '>' when '$gte' then '>=' when '$lt' then '<' else '<=' end, qx_lit(arg, p_typ));
    elsif op in ('$in', '$nin') then
      if jsonb_typeof(arg) <> 'array' then perform qx_fail('VALIDATION_ERROR', op || ' needs an array'); end if;
      has_null := false; lst := null;
      for el in select * from jsonb_array_elements(arg) loop
        if jsonb_typeof(el) = 'null' then has_null := true;
        else lst := coalesce(lst || ',', '') || qx_lit(el, p_typ); end if;
      end loop;
      lst := case when lst is null then 'false' else format('(%s = any (array[%s]::%s[]))', p_expr, lst, p_typ) end;
      if has_null then lst := format('(%s or %s is null)', lst, p_expr); end if;
      parts := parts || case when op = '$in' then lst else format('(not coalesce(%s, false))', lst) end;
    elsif op = '$exists' then
      parts := parts || case when arg = 'true'::jsonb then format('(%s is not null)', p_expr) else format('(%s is null)', p_expr) end;
    elsif op = '$regex' then
      if length(arg #>> '{}') > 200 then perform qx_fail('VALIDATION_ERROR', 'Regex too long'); end if;
      parts := parts || format('(%s::text %s %L)', p_expr, case when position('i' in opts) > 0 then '~*' else '~' end, arg #>> '{}');
    elsif op = '$options' then null;
    elsif op = '$not' then
      if jsonb_typeof(arg) <> 'object' then perform qx_fail('VALIDATION_ERROR', '$not needs an operator expression'); end if;
      parts := parts || format('(not coalesce(%s, false))', qx_cond(p_expr, p_typ, arg, depth + 1));
    else perform qx_fail('VALIDATION_ERROR', 'Unsupported operator ' || op);
    end if;
  end loop;
  return coalesce(array_to_string(parts, ' and '), 'true');
end $$;

create or replace function qx_where(p_t text, f jsonb, depth int default 0) returns text language plpgsql stable as $$
declare k text; v jsonb; parts text[] := '{}'; sub text; e text; ty text; x jsonb;
begin
  if depth > 8 then perform qx_fail('VALIDATION_ERROR', 'Filter too deeply nested'); end if;
  if f is null or jsonb_typeof(f) <> 'object' or f = '{}'::jsonb then return 'true'; end if;
  for k, v in select * from jsonb_each(f) loop
    if k in ('$and', '$or', '$nor') then
      if jsonb_typeof(v) <> 'array' then perform qx_fail('VALIDATION_ERROR', k || ' needs an array'); end if;
      sub := null;
      for x in select * from jsonb_array_elements(v) loop
        sub := coalesce(sub || case when k = '$and' then ' and ' else ' or ' end, '') || '(' || qx_where(p_t, x, depth + 1) || ')';
      end loop;
      if sub is null then sub := case when k = '$and' then 'true' else 'false' end; end if;
      parts := parts || case when k = '$nor' then 'not (' || sub || ')' else '(' || sub || ')' end;
    elsif left(k, 1) = '$' then perform qx_fail('VALIDATION_ERROR', 'Unsupported operator ' || k);
    else
      select * into e, ty from qx_field(p_t, k);
      parts := parts || qx_cond(e, ty, v, depth + 1);
    end if;
  end loop;
  return coalesce(array_to_string(parts, ' and '), 'true');
end $$;

-- sort: array of [field, dir] pairs (order preserved) or an object
create or replace function qx_order(p_t text, p_sort jsonb) returns text language plpgsql stable as $$
declare out text := ''; el jsonb; k text; d int; e text; ty text; kv record;
begin
  if p_sort is not null and jsonb_typeof(p_sort) = 'array' then
    for el in select * from jsonb_array_elements(p_sort) loop
      k := el ->> 0; d := coalesce((el ->> 1)::int, 1);
      select * into e, ty from qx_field(p_t, k);
      out := out || format('%s %s, ', e, case when d < 0 then 'desc nulls last' else 'asc nulls first' end);
    end loop;
  elsif p_sort is not null and jsonb_typeof(p_sort) = 'object' then
    for kv in select * from jsonb_each(p_sort) loop
      select * into e, ty from qx_field(p_t, kv.key);
      out := out || format('%s %s, ', e, case when (kv.value #>> '{}')::int < 0 then 'desc nulls last' else 'asc nulls first' end);
    end loop;
  end if;
  return out || 'r._seq asc';
end $$;

create or replace function qx_resolve(v jsonb, vars jsonb) returns jsonb language plpgsql immutable as $$
declare s text; root text; got jsonb; k text; x jsonb; arr jsonb := '[]'::jsonb; obj jsonb := '{}'::jsonb;
begin
  if jsonb_typeof(v) = 'string' then
    s := v #>> '{}';
    if left(s, 1) = '$' and length(s) > 1 then
      root := split_part(substr(s, 2), '.', 1);
      if vars ? root then
        got := vars #> string_to_array(substr(s, 2), '.');
        return coalesce(got, 'null'::jsonb);
      end if;
    end if;
    return v;
  elsif jsonb_typeof(v) = 'array' then
    for x in select * from jsonb_array_elements(v) loop arr := arr || jsonb_build_array(qx_resolve(x, vars)); end loop;
    return arr;
  elsif jsonb_typeof(v) = 'object' then
    for k, x in select * from jsonb_each(v) loop obj := obj || jsonb_build_object(k, qx_resolve(x, vars)); end loop;
    return obj;
  end if;
  return v;
end $$;

create or replace function qx_project(doc jsonb, proj jsonb) returns jsonb language plpgsql immutable as $$
declare inc boolean := false; k text; v jsonb; out jsonb := '{}'::jsonb; off text[];
begin
  if proj is null or jsonb_typeof(proj) <> 'object' or proj = '{}'::jsonb then return doc; end if;
  for k, v in select * from jsonb_each(proj) loop
    if k <> '_id' and v not in ('0'::jsonb, 'false'::jsonb, 'null'::jsonb) then inc := true; end if;
  end loop;
  if inc then
    for k, v in select * from jsonb_each(proj) loop
      if v not in ('0'::jsonb, 'false'::jsonb, 'null'::jsonb) and doc ? k then out := out || jsonb_build_object(k, doc -> k); end if;
    end loop;
    if coalesce(proj -> '_id', '1'::jsonb) not in ('0'::jsonb, 'false'::jsonb) and doc ? '_id' then out := out || jsonb_build_object('_id', doc -> '_id'); end if;
    return out;
  end if;
  select coalesce(array_agg(e.key), '{}') into off from jsonb_each(proj) e where e.value in ('0'::jsonb, 'false'::jsonb);
  return doc - off;
end $$;

create or replace function qx_docsql(v qx_tables, p_proj jsonb) returns text language sql immutable as $$
  select case when p_proj is null or jsonb_typeof(p_proj) <> 'object' then v.docexpr
              else format('qx_project(%s, %L::jsonb)', v.docexpr, p_proj::text) end $$;

-- ------------------------------------------------------------------ reads --
create or replace function qx_do_query(p_t text, p_filters jsonb, p_sort jsonb, p_skip int, p_limit int, p_proj jsonb default null) returns jsonb
language plpgsql stable as $$
declare v qx_tables := qx_tbl(p_t); w text := qx_where(p_t, p_filters); o text := qx_order(p_t, p_sort);
        total bigint; data jsonb; lim int := least(greatest(coalesce(p_limit, 100), 1), 1000); sk int := greatest(coalesce(p_skip, 0), 0);
begin
  execute format('select count(*) from %I r where %s', p_t, w) into total;
  execute format('select coalesce(jsonb_agg(d), ''[]''::jsonb) from (select %s as d from %I r where %s order by %s offset %s limit %s) s',
                 qx_docsql(v, p_proj), p_t, w, o, sk, lim) into data;
  return jsonb_build_object('success', true, 'data', data,
    'pagination', jsonb_build_object('page', sk / lim + 1, 'limit', lim, 'total', total, 'pages', ceil(total::numeric / lim)));
end $$;

create or replace function qx_do_get(p_t text, p_filters jsonb, p_sort jsonb, p_proj jsonb default null) returns jsonb language plpgsql stable as $$
declare v qx_tables := qx_tbl(p_t); doc jsonb;
begin
  execute format('select %s from %I r where %s order by %s limit 1', qx_docsql(v, p_proj), p_t, qx_where(p_t, p_filters), qx_order(p_t, p_sort)) into doc;
  return jsonb_build_object('success', true, 'data', doc);
end $$;

create or replace function qx_do_sum(p_t text, p_field text, p_filters jsonb, p_group jsonb) returns jsonb language plpgsql stable as $$
declare v qx_tables := qx_tbl(p_t); w text := qx_where(p_t, p_filters); ft text; fe text; ismoney boolean := false;
        n bigint; s numeric := 0; groups jsonb := '[]'::jsonb; gexprs text := ''; gk text; e text; ty text;
begin
  if p_field is not null then
    if not (v.coltypes ? p_field) then perform qx_fail('VALIDATION_ERROR', 'Unknown field'); end if;
    ft := v.coltypes ->> p_field; ismoney := ft = 'm'; fe := format('coalesce(r.%I, 0)', p_field);
  else fe := '0'; end if;
  execute format('select count(*), coalesce(sum(%s), 0) from %I r where %s', fe, p_t, w) into n, s;
  if p_group is not null and jsonb_array_length(p_group) > 0 then
    for gk in select jsonb_array_elements_text(p_group) loop
      if not (v.coltypes ? gk) then perform qx_fail('VALIDATION_ERROR', 'Unknown group field'); end if;
      gexprs := gexprs || format('r.%I::text, ', gk);
    end loop;
    execute format('select coalesce(jsonb_agg(jsonb_build_object(''key'', k, ''count'', c, ''sum'', %s)), ''[]''::jsonb) from (select jsonb_build_array(%s) as k, count(*) as c, sum(%s) as sm from %I r where %s group by %s order by min(r._seq)) g',
                   case when ismoney then 'to_char(sm, ''FM9999999999999990.00'')' else 'sm' end,
                   rtrim(gexprs, ', '), fe, p_t, w, rtrim(gexprs, ', ')) into groups;
  end if;
  return jsonb_build_object('success', true, 'data', jsonb_build_object('count', n,
    'sum', case when p_field is null then null when ismoney then to_jsonb(to_char(s, 'FM9999999999999990.00')) else to_jsonb(s) end,
    'groups', groups));
end $$;

create or replace function qx_ledger(p_filters jsonb) returns jsonb language plpgsql stable as $$
declare w text := qx_where('financial_ledger', coalesce(p_filters, '{}'::jsonb) || '{"status":"posted"}'::jsonb); o jsonb;
begin
  execute format($f$select jsonb_build_object(
      'total_credits',   to_char(coalesce(sum(amount) filter (where direction = 'credit'), 0), 'FM9999999999999990.00'),
      'total_debits',    to_char(coalesce(sum(amount) filter (where direction = 'debit'), 0), 'FM9999999999999990.00'),
      'total_earned',    to_char(coalesce(sum(amount) filter (where transaction_type = 'earning'), 0), 'FM9999999999999990.00'),
      'total_reversed',  to_char(coalesce(sum(amount) filter (where transaction_type = 'earning_reversal'), 0), 'FM9999999999999990.00'),
      'total_held_ever', to_char(coalesce(sum(amount) filter (where transaction_type = 'withdrawal_hold'), 0), 'FM9999999999999990.00'),
      'total_released',  to_char(coalesce(sum(amount) filter (where transaction_type = 'withdrawal_release'), 0), 'FM9999999999999990.00'))
    from financial_ledger r where %s$f$, w) into o;
  return o;
end $$;

-- ----------------------------------------------------------------- writes --
create or replace function qx_insert_one(p_t text, p_data jsonb) returns jsonb language plpgsql as $$
declare v qx_tables := qx_tbl(p_t); d jsonb := '{}'::jsonb; ex jsonb := '{}'::jsonb; k text; x jsonb; cols text; doc jsonb;
begin
  if p_data is null or jsonb_typeof(p_data) <> 'object' then perform qx_fail('VALIDATION_ERROR', 'data is required'); end if;
  for k, x in select * from jsonb_each(p_data) loop
    if k = '_extra' then continue; end if;
    if v.coltypes ? k then
      if jsonb_typeof(x) = 'null' and (k = '_id' or k = 'id' or k = v.id_field) then continue; end if;
      d := d || jsonb_build_object(k, x);
    else ex := ex || jsonb_build_object(k, x); end if;
  end loop;
  if ex <> '{}'::jsonb then d := d || jsonb_build_object('_extra', ex); end if;
  select string_agg(format('%I', key), ', ') into cols from jsonb_object_keys(d) key;
  if cols is null then perform qx_fail('VALIDATION_ERROR', 'data is required'); end if;
  execute format('insert into %I as r (%s) select %s from jsonb_populate_record(null::%I, $1) returning %s', p_t, cols, cols, p_t, v.docexpr)
    into doc using d;
  return doc;
end $$;

-- builds the SET list for an update document (Mongo subset: $set $inc $push $unset)
create or replace function qx_setlist(p_t text, p_update jsonb, p_now boolean default false) returns text
language plpgsql stable as $$
declare v qx_tables := qx_tbl(p_t); sets text[] := '{}'; ex_expr text := 'coalesce(r._extra, ''{}''::jsonb)'; touched_extra boolean := false;
        op text; body jsonb; k text; x jsonb; path text[]; base text; typ text; sd jsonb := '{}'::jsonb;
begin
  if p_update is null or jsonb_typeof(p_update) <> 'object' then perform qx_fail('VALIDATION_ERROR', 'update is required'); end if;
  for op, body in select * from jsonb_each(p_update) loop
    if op not in ('$set', '$inc', '$push', '$unset', '$setOnInsert') then perform qx_fail('VALIDATION_ERROR', 'Unsupported update operator ' || op); end if;
    if op = '$setOnInsert' then continue; end if;
    for k, x in select * from jsonb_each(body) loop
      if k !~ '^[A-Za-z0-9_.]+$' then perform qx_fail('VALIDATION_ERROR', 'Invalid field name'); end if;
      if k = v.id_field or k = '_id' or k = 'id' then perform qx_fail('VALIDATION_ERROR', k || ' is immutable'); end if;
      base := split_part(k, '.', 1); path := string_to_array(k, '.');
      if v.coltypes ? base and position('.' in k) = 0 then
        typ := v.coltypes ->> base;
        if op = '$set' then sd := sd || jsonb_build_object(k, x);
        elsif op = '$unset' then sets := sets || format('%I = null', k);
        elsif op = '$inc' then
          if typ not in ('i', 'f', 'm') then perform qx_fail('VALIDATION_ERROR', '$inc needs a numeric field'); end if;
          sets := sets || format('%I = coalesce(r.%I, 0) + %s', k, k, (x #>> '{}')::numeric);
        elsif op = '$push' then
          if typ <> 'j' then perform qx_fail('VALIDATION_ERROR', '$push needs a JSON field'); end if;
          sets := sets || format('%I = coalesce(r.%I, ''[]''::jsonb) || jsonb_build_array(%L::jsonb)', k, k, x::text);
        end if;
      elsif v.coltypes ? base and (v.coltypes ->> base) = 'j' then
        if op = '$set' then sets := sets || format('%I = jsonb_set(coalesce(r.%I, ''{}''::jsonb), %L, %L::jsonb, true)', base, base, path[2:], x::text);
        elsif op = '$unset' then sets := sets || format('%I = coalesce(r.%I, ''{}''::jsonb) #- %L', base, base, path[2:]);
        else perform qx_fail('VALIDATION_ERROR', 'Unsupported nested update'); end if;
      else  -- undeclared field -> _extra
        touched_extra := true;
        if op = '$set' then ex_expr := format('jsonb_set(%s, %L, %L::jsonb, true)', ex_expr, path, x::text);
        elsif op = '$unset' then ex_expr := format('(%s #- %L)', ex_expr, path);
        elsif op = '$inc' then ex_expr := format('jsonb_set(%s, %L, to_jsonb(coalesce((r._extra #>> %L)::numeric, 0) + %s), true)', ex_expr, path, path, (x #>> '{}')::numeric);
        elsif op = '$push' then ex_expr := format('jsonb_set(%s, %L, coalesce(r._extra #> %L, ''[]''::jsonb) || jsonb_build_array(%L::jsonb), true)', ex_expr, path, path, x::text);
        end if;
      end if;
    end loop;
  end loop;
  for k, x in select * from jsonb_each(sd) loop
    sets := sets || format('%I = (jsonb_populate_record(null::%I, %L::jsonb)).%I', k, p_t, jsonb_build_object(k, x)::text, k);
  end loop;
  if touched_extra then sets := sets || format('_extra = %s', ex_expr); end if;
  if array_length(sets, 1) is null then perform qx_fail('VALIDATION_ERROR', 'Empty update'); end if;
  return array_to_string(sets, ', ');
end $$;

-- returns {matched, modified, docs[], before[]}  (rows are locked FOR UPDATE: compare-and-set is race-free)
create or replace function qx_update_rows(p_t text, p_filters jsonb, p_update jsonb, p_max int, p_sort jsonb) returns jsonb
language plpgsql as $$
declare v qx_tables := qx_tbl(p_t); sel jsonb; pks text[]; res jsonb; lim text; modified int := 0; e jsonb; docs jsonb := '[]'::jsonb; before jsonb := '[]'::jsonb;
begin
  if v.append_only then perform qx_fail('FORBIDDEN_TABLE_OPERATION', p_t || ' is append-only'); end if;
  lim := case when p_max is null then '' else format('limit %s', p_max) end;
  execute format('select coalesce(jsonb_agg(jsonb_build_object(''pk'', pk, ''doc'', d)), ''[]''::jsonb) from (select r.%I::text as pk, %s as d from %I r where %s order by %s %s for update) s',
                 v.id_field, v.docexpr, p_t, qx_where(p_t, p_filters), qx_order(p_t, p_sort), lim) into sel;
  if jsonb_array_length(sel) = 0 then
    return jsonb_build_object('matched', 0, 'modified', 0, 'docs', '[]'::jsonb, 'before', '[]'::jsonb);
  end if;
  select array_agg(x ->> 'pk') into pks from jsonb_array_elements(sel) x;
  execute format('with u as (update %I as r set %s where r.%I::text = any ($1) returning r.%I::text as pk, %s as d) select coalesce(jsonb_agg(jsonb_build_object(''pk'', pk, ''doc'', d)), ''[]''::jsonb) from u',
                 p_t, qx_setlist(p_t, p_update), v.id_field, v.id_field, v.docexpr) into res using pks;
  for e in select * from jsonb_array_elements(sel) loop
    before := before || jsonb_build_array(e -> 'doc');
    docs := docs || jsonb_build_array((select x -> 'doc' from jsonb_array_elements(res) x where x ->> 'pk' = e ->> 'pk'));
  end loop;
  select count(*) into modified from jsonb_array_elements(before) with ordinality b(doc, n)
    join jsonb_array_elements(docs) with ordinality a(doc, n) using (n) where b.doc is distinct from a.doc;
  return jsonb_build_object('matched', jsonb_array_length(sel), 'modified', modified, 'docs', docs, 'before', before);
end $$;

create or replace function qx_find_one_and_update(p_t text, p_req jsonb) returns jsonb language plpgsql as $$
declare r jsonb; f jsonb := coalesce(p_req -> 'filters', '{}'::jsonb); upd jsonb := p_req -> 'update'; k text; c jsonb;
        seed jsonb := '{}'::jsonb; ins jsonb; created jsonb; x jsonb; kk text;
begin
  r := qx_update_rows(p_t, f, upd, 1, p_req -> 'sort');
  if (r ->> 'matched')::int > 0 then
    return case when p_req ->> 'return_document' = 'before' then r -> 'before' -> 0 else r -> 'docs' -> 0 end;
  end if;
  if coalesce((p_req ->> 'upsert')::boolean, false) is not true then return null; end if;
  for k, c in select * from jsonb_each(f) loop
    if left(k, 1) = '$' then continue; end if;
    if jsonb_typeof(c) <> 'object' then seed := seed || jsonb_build_object(k, c);
    elsif c ? '$eq' then seed := seed || jsonb_build_object(k, c -> '$eq'); end if;
  end loop;
  seed := seed || coalesce(upd -> '$setOnInsert', '{}'::jsonb) || coalesce(upd -> '$set', '{}'::jsonb);
  for kk, x in select * from jsonb_each(coalesce(upd -> '$inc', '{}'::jsonb)) loop seed := seed || jsonb_build_object(kk, x); end loop;
  for kk, x in select * from jsonb_each(coalesce(upd -> '$push', '{}'::jsonb)) loop seed := seed || jsonb_build_object(kk, jsonb_build_array(x)); end loop;
  created := qx_insert_one(p_t, seed);
  return case when p_req ->> 'return_document' = 'before' then null else created end;
end $$;

create or replace function qx_do_delete(p_t text, p_filters jsonb, p_max int) returns jsonb language plpgsql as $$
declare v qx_tables := qx_tbl(p_t); n int; lim text := case when p_max is null then '' else format('limit %s', p_max) end;
begin
  if v.append_only then perform qx_fail('FORBIDDEN_TABLE_OPERATION', p_t || ' is append-only'); end if;
  execute format('with d as (delete from %I where %I::text in (select r.%I::text from %I r where %s order by r._seq %s) returning 1) select count(*) from d',
                 p_t, v.id_field, v.id_field, p_t, qx_where(p_t, p_filters), lim) into n;
  return jsonb_build_object('deleted', n);
end $$;

create or replace function qx_guard(p_op jsonb) returns jsonb language plpgsql as $$
declare s jsonb; avail numeric; need numeric;
begin
  if p_op ->> 'type' <> 'balance_gte' then perform qx_fail('VALIDATION_ERROR', 'Unknown guard'); end if;
  if coalesce(p_op ->> 'publisher_id', '') = '' then perform qx_fail('VALIDATION_ERROR', 'publisher_id is required'); end if;
  -- serialises concurrent withdrawals of the same publisher (released at commit)
  perform pg_advisory_xact_lock(hashtextextended('wallet:' || (p_op ->> 'publisher_id'), 0));
  s := qx_ledger(jsonb_build_object('publisher_id', p_op ->> 'publisher_id'));
  avail := (s ->> 'total_credits')::numeric - (s ->> 'total_debits')::numeric;
  need := round((p_op ->> 'amount')::numeric, 2);
  if avail < need then
    perform qx_fail('INSUFFICIENT_BALANCE', 'Requested amount exceeds available balance (' || to_char(avail, 'FM9999999999999990.00') || ')');
  end if;
  return jsonb_build_object('available_balance', to_char(avail, 'FM9999999999999990.00'));
end $$;

create or replace function qx_run_write(op jsonb) returns jsonb language plpgsql as $$
declare t text := op ->> 'table'; r jsonb; f jsonb; many boolean := coalesce((op ->> 'many')::boolean, false); rows jsonb; x jsonb; out jsonb := '[]'::jsonb;
begin
  case op ->> 'op'
    when 'create' then
      if jsonb_typeof(op -> 'rows') = 'array' then
        for x in select * from jsonb_array_elements(op -> 'rows') loop out := out || jsonb_build_array(qx_insert_one(t, x)); end loop;
        return out;
      end if;
      return qx_insert_one(t, op -> 'data');
    when 'update' then
      if coalesce(op ->> 'id', '') = '' and (op -> 'filters') is null then perform qx_fail('VALIDATION_ERROR', 'id or filters is required'); end if;
      f := coalesce(op -> 'filters', '{}'::jsonb);
      if coalesce(op ->> 'id', '') <> '' then f := f || jsonb_build_object((qx_tbl(t)).id_field, op ->> 'id'); end if;
      r := qx_update_rows(t, f, coalesce(op -> 'update', jsonb_build_object('$set', op -> 'data')), case when many then null else 1 end, null);
      return jsonb_build_object('matched', r -> 'matched', 'modified', r -> 'modified', 'data', coalesce(r -> 'docs' -> 0, 'null'::jsonb));
    when 'delete' then
      if coalesce(op ->> 'id', '') = '' and (op -> 'filters') is null then perform qx_fail('VALIDATION_ERROR', 'id or filters is required'); end if;
      f := coalesce(op -> 'filters', '{}'::jsonb);
      if coalesce(op ->> 'id', '') <> '' then f := f || jsonb_build_object((qx_tbl(t)).id_field, op ->> 'id'); end if;
      return qx_do_delete(t, f, case when many then null else 1 end);
    when 'find_one_and_update' then
      return coalesce(qx_find_one_and_update(t, op), 'null'::jsonb);
    else perform qx_fail('INVALID_ACTION', 'Unknown operation');
  end case;
  return null;
end $$;

create or replace function qx_batch(p_ops jsonb) returns jsonb language plpgsql as $$
declare vars jsonb := '{}'::jsonb; results jsonb := '[]'::jsonb; op jsonb; cond jsonb; out jsonb; i int := 0;
begin
  if p_ops is null or jsonb_typeof(p_ops) <> 'array' or jsonb_array_length(p_ops) = 0 then perform qx_fail('VALIDATION_ERROR', 'operations must be a non-empty array'); end if;
  if jsonb_array_length(p_ops) > 50 then perform qx_fail('VALIDATION_ERROR', 'Too many operations (max 50)'); end if;
  for op in select * from jsonb_array_elements(p_ops) loop
    if op ? 'if' then
      cond := qx_resolve(to_jsonb('$' || (op ->> 'if')), vars);
      if cond = 'null'::jsonb or cond = 'false'::jsonb or cond = to_jsonb('$' || (op ->> 'if')) then
        results := results || jsonb_build_array(jsonb_build_object('skipped', true)); continue;
      end if;
    end if;
    op := qx_resolve(op, vars);
    out := case when op ->> 'op' = 'guard' then qx_guard(op) else qx_run_write(op) end;
    results := results || jsonb_build_array(coalesce(out, 'null'::jsonb));
    if coalesce(op ->> 'as', '') <> '' then vars := vars || jsonb_build_object(op ->> 'as', coalesce(out, 'null'::jsonb)); end if;
  end loop;
  return results;
end $$;

-- ------------------------------------------------------------- entry point --
create or replace function qx_exec(req jsonb) returns jsonb language plpgsql set search_path = public, pg_temp as $$
declare a text := req ->> 'action'; t text := req ->> 'table'; r jsonb; msg text;
begin
  begin
    case a
      when 'ping' then return jsonb_build_object('success', true, 'data', jsonb_build_object('service', 'digisnr-supabase', 'status', 'ok'));
      when 'get' then
        if coalesce(req ->> 'id', '') = '' then perform qx_fail('VALIDATION_ERROR', 'id is required'); end if;
        return qx_do_get(t, jsonb_build_object((qx_tbl(t)).id_field, req ->> 'id'), null, req -> 'projection');
      when 'find_one' then return qx_do_get(t, req -> 'filters', req -> 'sort', req -> 'projection');
      when 'query' then return qx_do_query(t, req -> 'filters', req -> 'sort', (req ->> 'skip')::int, (req ->> 'limit')::int, req -> 'projection');
      when 'list' then return qx_do_query(t, req -> 'filters', req -> 'sort', (req ->> 'skip')::int, (req ->> 'limit')::int, req -> 'projection');
      when 'count' then
        perform qx_tbl(t);
        execute format('select jsonb_build_object(''success'', true, ''data'', jsonb_build_object(''count'', count(*))) from %I r where %s', t, qx_where(t, req -> 'filters')) into r;
        return r;
      when 'sum' then return qx_do_sum(t, req ->> 'field', req -> 'filters', req -> 'group_by');
      when 'ledger_summary' then return jsonb_build_object('success', true, 'data', qx_ledger(req -> 'filters'));
      when 'create' then return jsonb_build_object('success', true, 'data', qx_run_write(jsonb_build_object('op', 'create', 'table', t, 'data', req -> 'data', 'rows', req -> 'rows')));
      when 'update' then return jsonb_build_object('success', true, 'data', qx_run_write(req || '{"op":"update"}'::jsonb));
      when 'delete' then return jsonb_build_object('success', true, 'data', qx_run_write(req || '{"op":"delete"}'::jsonb));
      when 'find_one_and_update' then return jsonb_build_object('success', true, 'data', qx_run_write(req || '{"op":"find_one_and_update"}'::jsonb));
      when 'batch' then return jsonb_build_object('success', true, 'data', qx_batch(req -> 'operations'));
      else perform qx_fail('INVALID_ACTION', 'Unknown action');
    end case;
  exception
    when sqlstate 'QX001' then
      get stacked diagnostics msg = message_text;
      return jsonb_build_object('success', false, 'error', msg::jsonb);
    when unique_violation then
      return jsonb_build_object('success', false, 'error', jsonb_build_object('code', 'DUPLICATE_KEY', 'message', 'Duplicate key'));
    when others then
      raise warning 'qx_exec failed: % (%)', sqlerrm, sqlstate;
      return jsonb_build_object('success', false, 'error', jsonb_build_object('code', 'ERROR', 'message', 'Storage error'));
  end;
  return null;
end $$;
