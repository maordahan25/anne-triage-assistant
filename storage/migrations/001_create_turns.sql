-- ═══════════════════════════════════════════════════════════════════════
-- אן — לוג השיחות האנונימי ב-Supabase (Postgres)
-- ═══════════════════════════════════════════════════════════════════════
-- מה זה: יצירת שתי הטבלאות שמאחורי storage/ — turns (הלוג החי) ו-
-- turns_synthetic (הדאטה הסינתטי לדשבורד ולמודל החיזוי). אותן 26
-- עמודות בדיוק כמו סכמת ה-SQLite, כולל אילוצי ה-CHECK: הפרטיות של הלוג
-- מובנית בסכמה עצמה (אין אף עמודת טקסט חופשי), ולא רק בקוד שכותב אליה.
--
-- איך מריצים: Supabase -> SQL Editor -> New query -> הדביקו והריצו.
-- הסקריפט אידמפוטנטי: אפשר להריץ אותו שוב בבטחה (create/add column/
-- create index -> if not exists), וגם אחרי הוספת עמודה לסכמה.
--
-- אבטחה: כל טבלה נוצרת עם RLS מופעל וללא אף policy, וההרשאות של anon
-- ושל authenticated נשללות ממנה במפורש — מפתח ה-anon הציבורי אינו יכול
-- לקרוא או לכתוב את הלוג. השרת מתחבר במחרוזת החיבור של הפרויקט
-- (SUPABASE_DB_URL), שאינה כפופה ל-RLS, ולכן הוא ממשיך לעבוד.
--
-- ⚠ אין לערוך את הקובץ ידנית: הוא נוצר מ-storage/pg_schema.py, שהוא
--   התרגום היחיד של הסכמה ל-Postgres —
--       python -m storage.pg_schema --write
--   ובדיקת אופליין משווה את הקובץ לפלט הפונקציה.
-- ═══════════════════════════════════════════════════════════════════════

-- ── public.turns — הלוג החי ──────────────────────────
create table if not exists public.turns (
    id bigint generated always as identity primary key,
    schema_version integer not null check (schema_version >= 1),
    ts_utc text not null check (ts_utc ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'),
    session_id text not null check (char_length(session_id) = 32 and session_id ~ '^[0-9a-f]+$'),
    turn_index integer not null check (turn_index >= 1),
    emergency integer not null check (emergency in (0, 1)),
    red_flags_count integer not null check (red_flags_count >= 0),
    consulted integer not null check (consulted in (0, 1)),
    consult_path text not null check (consult_path in ('none', 'direct', 'crew')),
    topic text check (topic is null or topic in ('wounds', 'anxiety', 'dehydration', 'cold', 'other')),
    illustration_id text check (illustration_id is null or (char_length(illustration_id) between 1 and 64 and illustration_id ~ '^[a-z0-9_]+$')),
    sources_count integer not null check (sources_count >= 0),
    filtered_sources_count integer not null check (filtered_sources_count >= 0),
    user_message_chars integer check (user_message_chars is null or user_message_chars >= 0),
    reply_chars integer not null check (reply_chars >= 0),
    llm_calls integer not null check (llm_calls >= 0),
    t_safety_gate double precision check (t_safety_gate is null or t_safety_gate >= 0),
    t_triage double precision check (t_triage is null or t_triage >= 0),
    t_consult double precision check (t_consult is null or t_consult >= 0),
    t_compose double precision check (t_compose is null or t_compose >= 0),
    t_total double precision check (t_total is null or t_total >= 0),
    tool_rag_search integer not null check (tool_rag_search >= 0),
    tool_locate_place integer not null check (tool_locate_place >= 0),
    tool_get_weather integer not null check (tool_get_weather >= 0),
    tool_get_current_time integer not null check (tool_get_current_time >= 0),
    tools_other integer not null check (tools_other >= 0),
    image_attached integer not null default 0 check (image_attached in (0, 1))
);
alter table public.turns add column if not exists schema_version integer not null check (schema_version >= 1);
alter table public.turns add column if not exists ts_utc text not null check (ts_utc ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$');
alter table public.turns add column if not exists session_id text not null check (char_length(session_id) = 32 and session_id ~ '^[0-9a-f]+$');
alter table public.turns add column if not exists turn_index integer not null check (turn_index >= 1);
alter table public.turns add column if not exists emergency integer not null check (emergency in (0, 1));
alter table public.turns add column if not exists red_flags_count integer not null check (red_flags_count >= 0);
alter table public.turns add column if not exists consulted integer not null check (consulted in (0, 1));
alter table public.turns add column if not exists consult_path text not null check (consult_path in ('none', 'direct', 'crew'));
alter table public.turns add column if not exists topic text check (topic is null or topic in ('wounds', 'anxiety', 'dehydration', 'cold', 'other'));
alter table public.turns add column if not exists illustration_id text check (illustration_id is null or (char_length(illustration_id) between 1 and 64 and illustration_id ~ '^[a-z0-9_]+$'));
alter table public.turns add column if not exists sources_count integer not null check (sources_count >= 0);
alter table public.turns add column if not exists filtered_sources_count integer not null check (filtered_sources_count >= 0);
alter table public.turns add column if not exists user_message_chars integer check (user_message_chars is null or user_message_chars >= 0);
alter table public.turns add column if not exists reply_chars integer not null check (reply_chars >= 0);
alter table public.turns add column if not exists llm_calls integer not null check (llm_calls >= 0);
alter table public.turns add column if not exists t_safety_gate double precision check (t_safety_gate is null or t_safety_gate >= 0);
alter table public.turns add column if not exists t_triage double precision check (t_triage is null or t_triage >= 0);
alter table public.turns add column if not exists t_consult double precision check (t_consult is null or t_consult >= 0);
alter table public.turns add column if not exists t_compose double precision check (t_compose is null or t_compose >= 0);
alter table public.turns add column if not exists t_total double precision check (t_total is null or t_total >= 0);
alter table public.turns add column if not exists tool_rag_search integer not null check (tool_rag_search >= 0);
alter table public.turns add column if not exists tool_locate_place integer not null check (tool_locate_place >= 0);
alter table public.turns add column if not exists tool_get_weather integer not null check (tool_get_weather >= 0);
alter table public.turns add column if not exists tool_get_current_time integer not null check (tool_get_current_time >= 0);
alter table public.turns add column if not exists tools_other integer not null check (tools_other >= 0);
alter table public.turns add column if not exists image_attached integer not null default 0 check (image_attached in (0, 1));
create index if not exists idx_turns_ts on public.turns (ts_utc);
create index if not exists idx_turns_session on public.turns (session_id);
alter table public.turns enable row level security;
revoke all on table public.turns from anon;
revoke all on table public.turns from authenticated;
grant all on table public.turns to service_role;
comment on table public.turns is 'אן — לוג שיחות אנונימי (לוג חי). אין בטבלה טקסט משתמש: אורכים, מונים וקטגוריות סגורות בלבד.';

-- ── public.turns_synthetic — הדאטה הסינתטי ───────────
create table if not exists public.turns_synthetic (
    id bigint generated always as identity primary key,
    schema_version integer not null check (schema_version >= 1),
    ts_utc text not null check (ts_utc ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'),
    session_id text not null check (char_length(session_id) = 32 and session_id ~ '^[0-9a-f]+$'),
    turn_index integer not null check (turn_index >= 1),
    emergency integer not null check (emergency in (0, 1)),
    red_flags_count integer not null check (red_flags_count >= 0),
    consulted integer not null check (consulted in (0, 1)),
    consult_path text not null check (consult_path in ('none', 'direct', 'crew')),
    topic text check (topic is null or topic in ('wounds', 'anxiety', 'dehydration', 'cold', 'other')),
    illustration_id text check (illustration_id is null or (char_length(illustration_id) between 1 and 64 and illustration_id ~ '^[a-z0-9_]+$')),
    sources_count integer not null check (sources_count >= 0),
    filtered_sources_count integer not null check (filtered_sources_count >= 0),
    user_message_chars integer check (user_message_chars is null or user_message_chars >= 0),
    reply_chars integer not null check (reply_chars >= 0),
    llm_calls integer not null check (llm_calls >= 0),
    t_safety_gate double precision check (t_safety_gate is null or t_safety_gate >= 0),
    t_triage double precision check (t_triage is null or t_triage >= 0),
    t_consult double precision check (t_consult is null or t_consult >= 0),
    t_compose double precision check (t_compose is null or t_compose >= 0),
    t_total double precision check (t_total is null or t_total >= 0),
    tool_rag_search integer not null check (tool_rag_search >= 0),
    tool_locate_place integer not null check (tool_locate_place >= 0),
    tool_get_weather integer not null check (tool_get_weather >= 0),
    tool_get_current_time integer not null check (tool_get_current_time >= 0),
    tools_other integer not null check (tools_other >= 0),
    image_attached integer not null default 0 check (image_attached in (0, 1))
);
alter table public.turns_synthetic add column if not exists schema_version integer not null check (schema_version >= 1);
alter table public.turns_synthetic add column if not exists ts_utc text not null check (ts_utc ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$');
alter table public.turns_synthetic add column if not exists session_id text not null check (char_length(session_id) = 32 and session_id ~ '^[0-9a-f]+$');
alter table public.turns_synthetic add column if not exists turn_index integer not null check (turn_index >= 1);
alter table public.turns_synthetic add column if not exists emergency integer not null check (emergency in (0, 1));
alter table public.turns_synthetic add column if not exists red_flags_count integer not null check (red_flags_count >= 0);
alter table public.turns_synthetic add column if not exists consulted integer not null check (consulted in (0, 1));
alter table public.turns_synthetic add column if not exists consult_path text not null check (consult_path in ('none', 'direct', 'crew'));
alter table public.turns_synthetic add column if not exists topic text check (topic is null or topic in ('wounds', 'anxiety', 'dehydration', 'cold', 'other'));
alter table public.turns_synthetic add column if not exists illustration_id text check (illustration_id is null or (char_length(illustration_id) between 1 and 64 and illustration_id ~ '^[a-z0-9_]+$'));
alter table public.turns_synthetic add column if not exists sources_count integer not null check (sources_count >= 0);
alter table public.turns_synthetic add column if not exists filtered_sources_count integer not null check (filtered_sources_count >= 0);
alter table public.turns_synthetic add column if not exists user_message_chars integer check (user_message_chars is null or user_message_chars >= 0);
alter table public.turns_synthetic add column if not exists reply_chars integer not null check (reply_chars >= 0);
alter table public.turns_synthetic add column if not exists llm_calls integer not null check (llm_calls >= 0);
alter table public.turns_synthetic add column if not exists t_safety_gate double precision check (t_safety_gate is null or t_safety_gate >= 0);
alter table public.turns_synthetic add column if not exists t_triage double precision check (t_triage is null or t_triage >= 0);
alter table public.turns_synthetic add column if not exists t_consult double precision check (t_consult is null or t_consult >= 0);
alter table public.turns_synthetic add column if not exists t_compose double precision check (t_compose is null or t_compose >= 0);
alter table public.turns_synthetic add column if not exists t_total double precision check (t_total is null or t_total >= 0);
alter table public.turns_synthetic add column if not exists tool_rag_search integer not null check (tool_rag_search >= 0);
alter table public.turns_synthetic add column if not exists tool_locate_place integer not null check (tool_locate_place >= 0);
alter table public.turns_synthetic add column if not exists tool_get_weather integer not null check (tool_get_weather >= 0);
alter table public.turns_synthetic add column if not exists tool_get_current_time integer not null check (tool_get_current_time >= 0);
alter table public.turns_synthetic add column if not exists tools_other integer not null check (tools_other >= 0);
alter table public.turns_synthetic add column if not exists image_attached integer not null default 0 check (image_attached in (0, 1));
create index if not exists idx_turns_synthetic_ts on public.turns_synthetic (ts_utc);
create index if not exists idx_turns_synthetic_session on public.turns_synthetic (session_id);
alter table public.turns_synthetic enable row level security;
revoke all on table public.turns_synthetic from anon;
revoke all on table public.turns_synthetic from authenticated;
grant all on table public.turns_synthetic to service_role;
comment on table public.turns_synthetic is 'אן — לוג שיחות אנונימי (דאטה סינתטי לניסוי). אין בטבלה טקסט משתמש: אורכים, מונים וקטגוריות סגורות בלבד.';

-- ── אימות (להרצה ידנית, לא חלק מהמיגרציה) ────────────────────────────
--   select table_name, count(*) as columns
--     from information_schema.columns
--    where table_schema = 'public'
--      and table_name in ('turns', 'turns_synthetic')
--    group by table_name;            -- מצופה: 27 (26 + id) לכל טבלה
--
--   select relname, relrowsecurity
--     from pg_class
--    where relname in ('turns', 'turns_synthetic');   -- מצופה: true
