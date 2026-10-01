# Anne — a smart Hebrew-language pre-triage assistant

**English** · [עברית](README.md)

**"Anne"** is a smart Hebrew-language pre-triage assistant. She holds a short
conversation with the user, performs an **initial anamnesis** (focused
questioning about the symptoms), and returns **safe home care** for mild
conditions — wounds/cuts, anxiety, dehydration and colds — or refers the user to
medical help when needed. The goal: to reduce unnecessary ER visits while keeping
the user safe.

> Final project in an AI course. An educational project — the information is
> intended for first aid only and is not a substitute for diagnosis or
> professional medical advice.

## How Anne works

The user sees a single persona — **Anne** — who accompanies the entire
conversation. Behind the scenes an agent team (CrewAI) operates, and every
conversation turn goes through the following stages:

1. **The safety gate (Dr. Dexter) + questioning (anamnesis) — in parallel:**
   Dr. Dexter, a super-agent, examines every turn and identifies red flags
   (chest pain, shortness of breath, neurological signs, self-harm thoughts and
   more) while Anne performs the anamnesis — asking short questions or deciding
   there is enough information and summarizing the case for a consult. Dexter's
   emergency verdict always wins: in an emergency there is no attempt to treat —
   an immediate referral to the ER / MDA 101 by location and time, and on risk of
   self-harm — ERAN 1201.
2. **Specialist consult (RAG):** when Anne identifies the topic (`topic_hint`) —
   the case goes **directly** to the matching specialist doctor (the fast path,
   with no manager): Dr. Wynds (wounds), Dr. Anziety (anxiety), Dr. DeHydra
   (dehydration) or Dr. Colde (colds); a deterministic safety net (keywords)
   fills in a missing hint when the topic is unambiguous. When the topic is
   genuinely unclear — the hierarchical routing mechanism (manager) delegates to
   the appropriate doctor. On the direct path the knowledge chunks from the
   Hebrew store (filtered by topic) and the weather context are **injected into
   the doctor in code** — deterministic retrieval, with no tool loop — and the
   doctor returns, in a single structured call, a recommendation that includes an
   `illustration_id` validated against the closed illustration list. The sources
   come exclusively from the current turn's retrieved chunks, and a source that
   does not exist in the store is filtered out in code and is never displayed.
   The weather context is checked when Anne identifies a locality in the user's
   words ("it was 34 degrees in Ra'anana today — that strengthens the suspicion
   of dehydration"); for the manager-path doctors the tools remain available as a
   backup, only when the context is genuinely needed.
3. **A reply in Anne's voice:** source-grounded home-care instructions with the
   source cited, phrased warmly and at eye level — the only voice the user hears.
   When a guided illustration is chosen, it is shown to the user: a steps block
   in the terminal + opening the PNG in the default application (disable with
   `ANNE_NO_IMAGE_OPEN=1`).

In addition: when the conversation is built, the embedding model is loaded in the
background (early warm-up, once per process), so the first RAG call does not wait
for the model (~2GB) to load; the time, date and weekday are injected
automatically into every agent on every turn (from `tools/clock.py`, with no LLM
call and no tool) — so Anne "knows" that it is now night or a weekend without
asking; in the same way, when a locality is mentioned, the weather is checked in
code and injected into both the consult and the phrasing; and every turn returns
performance and usage metrics (`timings`, `llm_calls` — counted at the source via
crewai's event bus, `tool_usage`, `filtered_sources`) that are printed with
`ANNE_VERBOSE=1`.

## Project structure

```
Anne/
├── data/                 # RAG knowledge base — 4 topics, Hebrew .md documents
│   ├── wounds/           #   wounds and cuts
│   ├── anxiety/          #   anxiety
│   ├── dehydration/      #   dehydration
│   ├── cold/             #   colds and chills
│   └── emergency_locations.json  # emergency destinations: national numbers, 14 hospitals,
│                         #   27 Terem branches and 23 Bikur Rofe branches (static, no network)
├── rag/                  # the RAG pipeline
│   ├── config.py         #   central parameters (paths, model, chunk sizes, top_k)
│   ├── chunking.py       #   splitting documents into chunks + metadata
│   └── embedding_store.py#   embeddings (e5) + storage/retrieval in Chroma
├── chroma_db/            # the built Vector DB (created automatically; not in version control)
├── tools/                # helper tools for the agent — all free and with no API key
│   ├── weather.py        #   current weather + daily max/min (Open-Meteo)
│   ├── location.py       #   geocoding: place name -> coordinates (Open-Meteo)
│   └── clock.py          #   current time and date (local datetime, no network)
├── llm/                  # the LLM definition layer
│   └── config.py         #   role->model/temperature mapping, and reading the key from .env
├── crew/                 # the agent team (CrewAI) — Stage 2
│   ├── schemas.py        #   structured output contracts: SafetyVerdict, SpecialistAdvice...
│   ├── red_flags.py      #   contextual detection: "chest pressure" vs. "pressure at work"
│   ├── streaming.py      #   the chunk pipe from crewai to the display (streaming reply)
│   ├── illustrations.py  #   the closed list + illustration_id validation
│   ├── emergency_referral.py # emergency destinations by location and time — from the local file only
│   ├── tools.py          #   CrewAI wrappers for the tools (topic-locked RAG, clock, location...)
│   ├── agents.py         #   Anne, 4 specialist doctors, Dr. Dexter (safety)
│   ├── crew.py           #   the hierarchical crew: a routing manager + the doctors
│   ├── pipeline.py       #   conversation-turn flow: safety -> Anne -> consult -> compose
│   └── main.py           #   entry point: interactive chat in the terminal
├── storage/              # anonymous conversation log — local SQLite or Supabase
│   ├── turn_log.py       #   the schema + init_db / log_turn / reset_log + scrub
│   ├── backend.py        #   the switch (ANNE_LOG_BACKEND) + graceful fallback to SQLite
│   ├── supabase_backend.py #   Postgres connection: SQLAlchemy+psycopg, pooler, password encoding
│   ├── pg_schema.py      #   the same schema in the Postgres dialect + migration script generator
│   ├── migrations/       #   001_create_turns.sql — to be run in the SQL Editor (RLS, no anon)
│   └── synthetic.py      #   synthetic data generator for the dashboard (python -m storage.synthetic)
├── dashboard/            # two Streamlit apps over the log (two ports)
│   ├── data.py           #   pure data layer (pandas) — tested offline
│   ├── ui.py             #   shared view layer: palette, CSS, charts, filters
│   ├── app.py            #   the overview dashboard + the admin button (port 8501)
│   └── ml_app.py         #   the educational prediction model page (port 8502)
├── ml/                   # prediction model over the log — educational ML demonstration (not clinical)
│   ├── dataset.py        #   load and prepare: features/target + excluding leaky columns
│   ├── models.py         #   the 4 models + the educational explanation and formulas of each
│   ├── train.py          #   train all models+evaluate+save (python -m ml.train)
│   └── predict.py        #   load the models and predict a probability (python -m ml.predict)
├── vision/               # vision layer: an image that enriches the intake (Pillow+numpy)
│   ├── ingest.py         #   security: type by content, limits, EXIF removal, downscaling
│   ├── quality.py        #   (a) is the image usable — sharpness and exposure
│   ├── features.py       #   (b) deterministic measurements — redness, concentration, brightness
│   ├── describe.py       #   (c) a verbal description from the vision model — describes, never diagnoses
│   ├── scope.py          #   the scope boundary: a description outside the topics forbids treatment
│   └── analyze.py        #   analyze_image() -> ImageAnalysis + context for the prompt
├── server/               # the server wrapper (FastAPI) — connects the browser to the pipeline
│   ├── app.py            #   /api/chat, /api/welcome, /admin + /api/admin/*
│   └── documents.py      #   the project documents: a closed list + parsing for display
├── web/                  # the browser interface (RTL, Hebrew) — HTML/CSS/JS only
│   ├── index.html        #   Anne's chat + the "admin login" button
│   ├── style.css         #   the chat styling (tokens from assets/colors.css)
│   ├── app.js            #   the chat logic + an anonymous user id from localStorage
│   ├── demo.js           #   runs the demo scenarios (types and sends like a user)
│   ├── admin.html        #   the admin area: login, board, and the document viewer
│   ├── admin.css         #   styling of the admin area and the viewer (same design language, RTL)
│   ├── admin.js          #   the login gate + the document renderer registry
│   ├── credit.js         #   the credit in the browser (mirrors credit.py, inline SVG)
│   ├── a11y.css          #   the shared accessibility layer (sr-only, focus, contrast)
│   └── a11y.js           #   the accessibility panel + shared alt text for illustrations
├── illustrations/        # treatment illustrations (PNG) + illustrations.json (source of truth)
├── docs/                 # the project documents (shown in the admin area, read live)
│   ├── specification.md     # the specification document — 13 chapters: goals, scope, requirements,
│   │                        #   architecture, data model and safety boundaries
│   ├── accessibility.md     # accessibility statement (also served publicly at /accessibility)
│   └── demo_scenarios.json  # the source of truth for the demo scenarios and the runner
├── assets/               # logo, avatar, color palette (colors.css / palette.json)
│   └── demo/             #   demo image for the vision scenario (AI-generated for the project)
├── credit.py             # personal credit and branding — one source of truth for every screen
├── build_index.py        # building the Vector DB end-to-end (chunk→embed→store)
├── geocode_emergency_locations.py  # one-off: filling in coordinates for the emergency destinations
├── test_anne_suite.py    # the test suite: every check is mapped to a presentation slide;
│                         #   10 live scenarios (paid LLM) + --offline for free
├── llm_requirements.txt  # dependencies (a deliberately non-standard name)
└── .env.example          # environment variable template (LLM provider, API keys,
                          #   and the admin area credentials — placeholders only)
```

## What already works

### Knowledge base and RAG ✅ built and tested

The semantic retrieval pipeline is running end-to-end:
`chunking → embeddings → Chroma → retrieval`.

- **The data:** `data/` is split into 4 subdirectories by topic, and the
  subdirectory name is the `topic` tag. Each `.md` file is built from 4 sections
  under `##` headings (symptoms · first aid · continued care · immediate
  referral), and at its bottom a `מקור:` (source) line with the name and origin
  of the information. The sources are official medical ones (health funds, MDA)
  and well-known guides.

  | topic | Domain |
  |-------|------|
  | `wounds` | wounds and cuts |
  | `anxiety` | anxiety |
  | `dehydration` | dehydration |
  | `cold` | colds and chills |

- **Chunking** (`rag/chunking.py`): splitting by `##` headings — each section is
  an independent unit of meaning. A long section is split into ~600 characters
  with a ~70-character overlap, while keeping lines (the bullets) intact. Each
  chunk carries metadata: `topic`, `section`, `source`, `title`, `source_file` —
  for focused filtering and source citation.

- **Embeddings** (`rag/embedding_store.py`): `intfloat/multilingual-e5-large` — a
  local multilingual model that suits Hebrew well, free and with no API key. The
  e5 family requires prefixes: `passage:` for documents and `query:` for queries
  (applied automatically).

- **Storage and retrieval** ([Chroma](https://www.trychroma.com/)): a local,
  open-source Vector DB that persists to disk and supports filtering by
  `metadata`. Similarity is computed in cosine space. Retrieval returns the
  chunks closest in meaning, with optional filtering by `topic`.

### Helper tools (tools) ✅ ready

Three clean, independently testable tools, **all free and with no API key**. Each
tool returns a `dict` and never crashes — on failure it returns
`{"ok": False, "error": ...}`:

- `weather` — current weather + daily maximum/minimum by coordinates (Open-Meteo).
- `location` — geocoding: place name (Hebrew/English) -> coordinates (Open-Meteo).
- `clock` — current time and date with time zone support (local datetime, no network).

### The LLM layer ✅ configured

`llm/config.py` allows easy switching between providers (OpenAI / Anthropic)
through `LLM_PROVIDER` in `.env`, without touching the code. Every role is mapped
to a model tier and a temperature:

| Role | Tier | Temperature |
|-------|------|----------|
| Anne / intake | mid | 0.35 |
| Safety (Dr. Dexter) | strong | 0.1 |
| Specialists (doctors) | economical | 0.25 |
| Manager / routing | economical | 0.1 |

The API keys are read from the environment (`.env`); see `.env.example` for the
template. From that same file, `ADMIN_EMAIL` and `ADMIN_PASSWORD` are also read —
the admin area credentials, which do not exist in the code at all.

### Treatment illustrations ✅ ready

20 explanatory illustrations (PNG) that accompany the treatment instructions.
`illustrations/illustrations.json` is the source of truth — it links every
`illustration_id` to an image, a name, a category and the treatment steps in
Hebrew (for example `breathing_exercise`, `wound_cleaning`, `rehydration_sips`).

### The agent team (CrewAI) ✅ built

The full agent layer on top of the RAG and the tools (`crew/`):

- **One persona, a whole team:** Anne is the lead and the only voice; the
  specialist doctors and the routing manager operate behind the scenes,
  transparent to the user.
- **Orchestration in two paths:** when Anne identifies the topic — the specialist
  doctor runs directly (`Agent.kickoff`, the fast path, with no delegation
  rounds): a tool-less doctor into whom the store chunks and the weather context
  are injected in code — a single structured call, fast and stable; a
  deterministic safety net fills in a missing routing hint when the topic is
  unambiguous. When the topic is unclear — CrewAI's hierarchical Process:
  `manager_llm` (economical tier, temperature 0.1) delegates the case to the
  appropriate doctor (where the doctors do have full tools). Anne always runs
  outside the crew (`Agent.kickoff`) so that the final voice is hers alone.
- **Performance:** the safety gate and the anamnesis run in parallel; the
  embedding model is loaded in the background right at the start of the
  conversation (early warm-up); and every turn returns stage timings, an LLM call
  count and tool invocation counters for measurement (`ANNE_VERBOSE=1`).
- **Context awareness without asking:** the time and date are injected into every
  agent on every turn (a free Python call, with no tool round); when Anne
  identifies a locality in the user's words — the system checks location and
  weather in code and injects the result into both the consult and the phrasing
  of the reply, so the context always reaches the user.
- **Source faithfulness (two layers):** the transcript served to the agents is
  cleaned of the source lines of previous replies, and the doctors are required to
  copy exactly and only the retrieved sources of the current turn; in addition, a
  code layer filters out any source that matches no `מקור:` line in the store — an
  invented source never reaches the user, and on `topic=other` the sources field
  is always empty. There is no source "leakage" between turns or between topics. A
  greeting or smalltalk is never routed to a consult, and Anne never writes
  treatment steps herself — a `reply` that looks like treatment is converted in
  code into a team consult (deterministic guards in addition to the instructions).
- **Safety as the ultimate authority:** Dr. Dexter (the strong model, temperature
  0.1) examines every conversation turn before any treatment; an emergency verdict
  stops the whole team and returns a referral by location and time. A technical
  failure in the verdict never silences it — there is a fixed referral text
  (fallback) in the code.
- **"לחץ" — a contextual rather than a literal distinction:** in Hebrew "לחץ" is
  both psychological stress and physical pressure, and detection by a single word
  stopped anxiety conversations for nothing. Now pressure or pain is a red flag
  only when it is tied to the chest or the heart, or accompanied by radiation to
  the hand/arm/jaw, cold sweat, nausea or shortness of breath — and "pressure at
  work", "stressed before an interview", "tension", "psychological stress" and
  "social pressure" are not a red flag.
  **The sensitivity was not reduced:** alongside the sharpened instruction, a
  safety net was added in code (`crew/red_flags.py`) that can only *escalate* — an
  unambiguous description of chest pressure/pain guarantees an emergency verdict
  even if the model missed it, and it never cancels an existing verdict. Tested in
  both directions: 12 real emergency phrasings and 16 anxiety/stress complaints.
- **Real emergency destinations, from the code and not from the model:** when an
  emergency has been identified and a locality was mentioned in the conversation, a
  destination list is attached to the reply, built in
  `crew/emergency_referral.py` from `data/emergency_locations.json` — the nearest
  hospitals, and the Bikur Rofe and Terem branches that are open *at that very
  hour* (including night shifts and days marked closed). Dexter writes only the
  human paragraph; names, phone numbers, addresses and hours never come from him.
  A central safety distinction: on a critical red flag — 101 first and prominent,
  and the urgent-care centers are shown with an explicit warning that they are not
  the destination for this situation; in a state that requires a doctor but is not
  an emergency — an urgent-care center is the destination and the ER is the backup.
  All three headings (hospitals · Bikur Rofe · Terem) are always shown, even when
  there is nothing to show under them, and at the bottom always the health funds'
  hotlines. A locality that is not in the store — the fixed national text stands.
  **There is no network call during a conversation**: the file is static and the
  coordinates were filled in ahead of time by a one-off script.
- **Structured and validated output:** the doctor returns `SpecialistAdvice`
  (Pydantic) including an `illustration_id`; an id that is not in the closed list
  of `illustrations.json` is coerced to `None` — better no illustration than a
  misleading one. Each doctor sees only its own topic's illustration category (+
  "general"), and if the model did not pick an illustration even though it
  recommended an illustrated action — deterministic keyword matching completes the
  choice (only on a clear match).
- **Privacy:** crewai telemetry is off by default in the code.

### Anonymous conversation log (storage/) ✅ built and tested

Every conversation turn is recorded automatically as a structured, anonymous
record in SQLite (`anne_log.db`, the standard library's `sqlite3` — with no
external dependency). The log is the foundation for data analysis, for a future
dashboard and for a prediction model — and it is designed from the ground up so
that it *cannot* contain identifying details.

**Privacy by design in three layers:**

1. **The schema itself** — there is not a single free-text column: the user
   message and the reply are stored as lengths only, red flags and sources as
   counts only, and the tool counters are mapped to fixed columns (an unknown tool
   name is counted in `tools_other` without the name being stored). The only text
   columns are identifiers in a strict format or a closed vocabulary.
2. **`scrub_record`** — every value is validated against a per-column validator
   before the write: free text in a closed field is filtered down to a safe
   default, and an invalid identity field rejects the whole record; keys that are
   not in the schema are discarded.
3. **CHECK constraints in SQL** — even a direct write that bypasses the code is
   blocked by the database itself.

`session_id` is a random uuid created for every `ChatSession` — it groups the
turns of one conversation with no connection whatsoever to the user's identity.
The recording is best-effort in two try/except layers: a failure in the log never
brings down the conversation and never changes the reply, and the write (a single
INSERT, milliseconds) does not slow the turn down.

**The `turns` table schema:**

| Column | Type | Content |
|---|---|---|
| `id` | INTEGER | running primary key |
| `schema_version` | INTEGER | the schema version (currently 1) |
| `ts_utc` | TEXT | UTC timestamp in the strict format `YYYY-MM-DDTHH:MM:SSZ` |
| `session_id` | TEXT | a random uuid4 hex per conversation (exactly 32 hex characters) |
| `turn_index` | INTEGER | the turn's number within the conversation (from 1) |
| `emergency` | INTEGER | 0/1 — the safety gate's emergency verdict |
| `red_flags_count` | INTEGER | the number of red flags (without their content) |
| `consulted` | INTEGER | 0/1 — whether a specialist consult completed successfully |
| `consult_path` | TEXT | `none` / `direct` / `crew` — the consult path attempted |
| `topic` | TEXT | a topic from a closed list (wounds/anxiety/dehydration/cold/other) or NULL |
| `illustration_id` | TEXT | an illustration id from the closed list (an English slug) or NULL |
| `sources_count` | INTEGER | the number of sources cited |
| `filtered_sources_count` | INTEGER | the number of sources filtered out as unknown (observability) |
| `user_message_chars` | INTEGER | the length of the user message in characters (the text itself is not stored) |
| `reply_chars` | INTEGER | the length of Anne's reply in characters |
| `llm_calls` | INTEGER | LLM calls completed in the turn (counted on the event bus) |
| `t_safety_gate`, `t_triage`, `t_consult`, `t_compose`, `t_total` | REAL | the stage durations in seconds |
| `tool_rag_search`, `tool_locate_place`, `tool_get_weather`, `tool_get_current_time`, `tools_other` | INTEGER | the tool invocation counters for the turn |

Note: `consult_path` records the path that was attempted even when the consult
failed technically (`consulted=0`) — it distinguishes "did not consult" from
"consulted and fell back to the fallback".

**API:** `init_db()` · `log_turn(result, ...)` (lenient, returns a bool) ·
`write_record()` (strict, always through scrub) · `write_records()` (many, in one
transaction) · `reset_log()` (deleting all records — the admin button in the
dashboard) · `fetch_turns()`. The file path can be overridden with
`ANNE_LOG_DB`. `anne_log*.db` files are not in version control.

#### Two backends: local SQLite or Supabase (Postgres) ✅ built and tested

That exact same schema has two implementations, and the choice between them is
**one line in `.env`**:

```bash
ANNE_LOG_BACKEND=sqlite     # the default — a local file, standard library only
ANNE_LOG_BACKEND=supabase   # managed Postgres in the cloud
ANNE_LOG_TABLE=turns        # turns (the live log) / turns_synthetic (synthetic data)
# The connection string: Supabase → Connect → Transaction pooler (for why this
# one and not the Direct connection — see below)
SUPABASE_DB_URL=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://PROJECT_REF.supabase.co     # the project identity
SUPABASE_SERVICE_KEY=...                          # (for later stages)
```

- **No signature changed.** The switch sits *below* the API:
  `storage/backend.py` resolves a target (`Target`), and
  `storage/supabase_backend.py` holds the connection. `crew/pipeline.py`, the
  dashboard and the prediction model have no idea which backend they are running
  on — an offline check compares the parameter names of every function to a fixed
  list, so a signature change fails immediately.
- **A graceful fallback, not a crash.** Missing settings, a missing package or a
  failed connection return the log to local SQLite with **one warning to the
  log** — the conversation continues and the turn is recorded locally. The
  fallback is sticky for the whole process on purpose (a turn that waits for a
  timeout on every message is worse than a declared local log), and the dashboard
  shows a note instead of pretending that the data is from the cloud.
- **`SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are not used by this layer** — it
  speaks Postgres directly and not through the REST API. They are declared as the
  project identity (for example for access through the Supabase console), and not
  as keys this code consumes.

**Setting up the schema (once):** Supabase → **SQL Editor** → New query → paste
and run `storage/migrations/001_create_turns.sql`. The script is idempotent, it
creates both tables with the same 26 columns and the CHECK constraints, and it
secures them: **RLS enabled with no policy at all + revoking permissions from
`anon` and from `authenticated`** — meaning the public key in the browser can
neither read nor write the log. The file is generated from `storage/pg_schema.py`
(`python -m storage.pg_schema --write`), and an offline check compares the two so
that it cannot go stale.

**The Transaction pooler vs. a direct connection.** What you paste into
`SUPABASE_DB_URL` is the **Transaction pooler** string (port **6543**) — it is
the one that works from an ordinary IPv4 network, and it is the starting point
rather than the backup. The **Direct connection** (port **5432**) is not its
equivalent: the host `db.PROJECT_REF.supabase.co` publishes an **AAAA (IPv6)
record only** and has no A record, so on a network without IPv6 connectivity it
is simply unreachable — and that is not a misconfiguration on your side. Measured
on this project: `dig A` on the direct host returns nothing and `dig AAAA`
returns a single address, while the pooler's host returns three IPv4 addresses.

```bash
# This is the string to paste (Supabase → Connect → Transaction pooler):
SUPABASE_DB_URL=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres

# Optional, and relevant only if you deliberately chose the direct one in
# SUPABASE_DB_URL: the pooler is tried when the direct one fails. When the
# primary is already the pooler — this adds nothing.
SUPABASE_DB_URL_POOLER=postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
```

The code detects a pooler by the port or the host name and swaps settings
accordingly: no local pool (`NullPool`) and no prepared statements
(`prepare_threshold=None`) — pgbouncer's two requirements in transaction mode.
The pooler's host name includes the region and therefore **cannot be derived**
from the direct string; that is the reason the automatic backup requires pasting
it too.

**A momentary network fault leaves the process on SQLite until it is
restarted.** The fallback is sticky for the whole process (see above), so a short
network interruption while the server or a Streamlit app is starting up is enough
for every turn after it to be written locally — even after the network has
recovered on its own. The sign: `describe_target()` and the dashboard's note say
SQLite even though `ANNE_LOG_BACKEND=supabase`. The fix is to restart the
process, without touching any setting.

**The password is encoded automatically.** A password generated in Supabase may
contain `@ / : # %` and a space — each of which breaks a connection string.
`normalize_db_url` splits the string manually (cutting at the **last** `@`,
because `urlsplit` breaks on exactly such a password), URL-encodes the password
without double encoding, and fills in `sslmode=require`. There is no need to
encode manually, and the password is not written to any log.

**What else works on top of both backends:** a "live / synthetic" switch in both
Streamlit apps picks a **table** (`turns` / `turns_synthetic`) and does not swap
the connection; the prediction model trains on the active data source; and
`python -m storage.synthetic` seeds the table in Supabase with the same command
(`--db turns_synthetic`, or the default that maps to it) and prints the target it
**actually** reached at the end.

### Analytics dashboard + prediction page (dashboard/) ✅ built and tested

**Two separate Streamlit apps** over the same anonymous log (local, free, no
LLM), each on its own port:

```bash
streamlit run dashboard/app.py --server.port 8501     # overview → :8501
streamlit run dashboard/ml_app.py --server.port 8502  # prediction → :8502
```

It used to be one app with two tabs. The split gives three things: every page can
be run, demoed and restarted separately; a crash in one page does not bring down
the other; and the two buttons in the admin area each point at their own app and
are probed separately. The shared code (data loading, branding, palette, charts,
filters) sits once in `dashboard/ui.py` — both consume it, neither duplicates it.

- **What you see (the overview app):** a KPI row (turns, conversations,
  emergencies, consult rate, median turn duration, LLM calls per turn), a daily
  trend with emergency days marked, breakdowns of topics and consult paths, the
  average duration of every stage in the pipeline, LLM cost by path (direct vs.
  crew), tool usage, the most common illustrations, the conversation-length
  distribution, and a full table with CSV export.
- **An explanation above every chart:** 2-3 sentences explaining what the chart
  type shows and how the metric is defined — a fixed explanation and not an
  interpretation of the current numbers (they change with every filter and with
  every new conversation).
- **Legible labels:** all the category charts are horizontal and full-row width,
  with physical space reserved for the longest label (a computed gutter), a
  generous truncation ceiling, an explicit pixel height and headroom at the end of
  the scale for the value label — so that a Hebrew label is read in full even in a
  narrow chart. The illustrations chart shows Hebrew names from the catalog and not
  English file ids.
- **Branding:** Anne's logo as the tab icon, at the top of the sidebar and in the
  page header; Anne's figure at the bottom of the sidebar; KPI tiles, section
  headings and the explanation cards in the brand palette from
  `assets/colors.css` — the same visual language as the chat and the admin area.
- **The prediction app 🔮 (`dashboard/ml_app.py`, port 8502):** the educational
  prediction model (`ml/`) as a standalone page — a "not a clinical tool" warning
  at the top of the page, a card per model (an accessible explanation + the
  held-out sample metrics + the mathematics), a training button on the selected log
  file, an interactive ("what-if") prediction over the four features, and the
  scatter of the predicted probabilities on the filtered data against the actual
  emergencies. It also functions with no trained model (a hint to train), without
  scikit-learn (a dependencies message) and even when the log is empty (the
  educational content stays, only the scatter plot is replaced by an explanation).
- **Filters:** date range, topics, consult path, emergency-only; log file
  selection (real / synthetic / `ANNE_LOG_DB`).
- **Admin button 🗑️:** resetting the log (`storage.reset_log`) with double
  confirmation — the button is locked until a confirmation checkbox is ticked, and
  the deletion is final (DELETE + VACUUM).
- **⚠️ The gate on administrative actions — locked by default, in every
  deployment:** resetting the log and training the models are locked by default
  (`dashboard/admin_access.py`). The deletion is final, and in Supabase mode it
  deletes the table **in the cloud** — and therefore in a cloud deployment these
  actions are simply **not created in the page at all**: not a button, not a
  confirmation checkbox and not even the card that wraps them.
  **Who can reach the app is not something the repo can know:** viewer
  permissions are a setting in the hosting service, and making an app public is
  one click that leaves no trace in Git. At the last check both apps in fact
  *required* authentication (every path, the health check included, redirects to
  a login screen) — and that can flip back without a single commit. So the code
  assumes neither state, and the gate is what makes the answer independent of
  them.
  For local operation add `ANNE_DASHBOARD_ADMIN_CODE` (at least 8 characters) to
  `.env` and you will get a code field in the sidebar; only a correct code reveals
  the action.
  The principle is **locked by default**: there is no guessing here of "am I
  running locally" (such a guess fails *open* the day the signal changes, and a
  `Host` header can also be forged) but rather reliance on one thing that exists
  locally and does not exist in the cloud — a code in `.env`, which is not in
  version control. `ANNE_PUBLIC_DEPLOY=1` blocks it even if a code was defined by
  mistake in the deployment's secrets, and a Streamlit Cloud deployment is also
  detected automatically by the run path. The remaining actions in both apps are
  read-only (cache refresh, CSV export, filters).
- **Design:** Anne's brand theme (`assets/palette.json`, also defined in
  `.streamlit/config.toml`), Hebrew RTL, and category colors assigned fixedly per
  entity that passed accessibility validation (color blindness, contrast); the
  safety red is reserved for emergencies only. Streamlit telemetry is off —
  consistent with the project's policy.
- **Layer separation:** `dashboard/data.py` is pure pandas (aggregations only),
  `dashboard/ui.py` is the shared view layer, and `app.py`/`ml_app.py` are page
  content only. All three are tested in the offline suite — including a full run
  of **both** apps in AppTest (with no browser and no port) in three data states:
  full data, a degenerate filter (emergency only) and an empty log.
- **A regression check on the chart contract:** a real bug brought the dashboard
  down when `illustration_counts` moved to displaying Hebrew names and the display
  column changed its name — and it also brought down the prediction page, which
  was then a tab in the same app. Today `category_bar` raises an error that
  **names the missing column**, and an offline check verifies that every
  aggregation returns a `label` column in every data state and that every chart is
  really built from it.

### Prediction model (ml/) ✅ built and tested — an educational demonstration

> ⚠️ **A Machine Learning capability demonstration only — not a clinical tool.**
> The model is trained on synthetic data and on a small sample (emergencies ~4% of
> the turns); its metrics must not be presented as clinical accuracy and it must
> not be used for medical assessment.

A scikit-learn model that predicts, from a single log record, the probability that
the turn will end in an ER referral — the target is the `emergency` column (the
verdict of Dexter's safety gate, the conceptual meaning of referred_to_er). Free,
no LLM.

- **features — only what is known at the start of the turn:** the topic
  (`topic`), the position in the conversation (`turn_index`), the message length
  (`user_message_chars`) and the hour from `ts_utc` (cyclic sin/cos encoding).
  Every column that is a *product* of the emergency verdict (red flags, consult
  path, timings, tool counters...) is excluded explicitly — preventing target
  leakage, enforced by the offline check over the whole schema.
- **Four models on the same task and the same split** (the comparison is the
  educational point): **logistic regression** (the default — the transparent one,
  odds ratios can be read from it), **random forest** (an average of hundreds of
  decision trees), **gradient boosting** (sequential trees that correct one
  another), and a **baseline model** that does not learn — a reference line with a
  ROC-AUC of exactly 0.5, so that there is something to compare against. All of
  them go through the same preprocessing (one-hot for the topic,
  imputation+standardization for the numerics) and are trained on exactly the same
  split. They are saved together as one joblib bundle to `ml/models/` (not in
  version control — rebuilt with one command). All the models ship inside
  scikit-learn — there is no new dependency.
- **An educational page in the dashboard:** a card per model with an explanation
  in plain Hebrew, its metrics, and a "🧮 the mathematics" tab with the formulas
  (sigmoid and log-loss, Gini and the variance of the average, the boosting
  update) and a Hebrew explanation for each formula; a metric glossary (ROC-AUC,
  Average Precision, Recall, Precision, Brier — and why "accuracy" does not appear
  when emergencies are 4%); a "what the model looks at" chart; and an interactive
  prediction that runs *all* the models on the same input.
- **An integrity note that is shown on the page:** the strongest feature comes out
  as "no topic" — not because of a medical insight but because a turn that was
  stopped in an emergency never gets a topic at all. This is a live example of
  proxy leakage, and it is explained on the page instead of hidden.
- **Prediction:** `predict_er_probability(record)` returns a single probability in
  the range [0,1], even on a partial record; `predict_frame(df)` scores a whole
  DataFrame (the prediction page's path). The model path can be overridden with
  `ANNE_ML_MODEL` (like `ANNE_LOG_DB`). A calibration note: the class balancing
  inflates the absolute probabilities — the relative ordering between cases is
  what is meaningful.
- **The interface:** `dashboard/ml_app.py` — a separate Streamlit app (port 8502)
  with a card per model, training at the click of a button, interactive prediction
  and the scatter of the probabilities against the actual emergencies. `ml/` itself
  stays free of Streamlit.
- **Tests (offline, free):** feature integrity (zero leakage), deterministic
  training on synthetic data, save/load with an identical prediction, valid
  probabilities (single and batch), and the prediction app running in AppTest with
  a model and without one.

### The browser wrapper and the admin area (server/ + web/) ✅ built and tested

A thin FastAPI server that serves the chat interface in the browser and connects
it to the existing pipeline. **A wrapper only:** the single call inward is
`ChatSession.run_turn` — there is no agent or RAG logic here.

- **The chat (`/`):** an RTL interface in Hebrew with conversation bubbles, a
  guided illustration card, an emergency banner and a sources line. The browser
  generates an anonymous id (`localStorage`) and sends it with every message; the
  server maps it to a live conversation, so the conversation continues between
  messages. The id is never written to the log — the structural privacy of
  `storage/` is preserved.
- **A streaming reply (SSE):** the reply appears while Anne is phrasing it, and
  until then the current stage is displayed ("checking the message…", "consulting
  with the medical team…", "phrasing the reply…"). The turn duration has not
  changed — the *perceived* time has. If streaming is not available, the browser
  falls back automatically to the regular path (`/api/chat`).
- **The source is displayed once:** the `מקור:` line is removed from the reply body
  before it is sent to the browser, and the UI displays the sources once — from the
  field validated against the store. A display-only fix; the agent instructions and
  the transparency were untouched.
- **The admin area (`/admin`):** a login screen and a management board styled in
  the same design language (based on the project's Stitch screen, branded with the
  logo and the palette). On the board: a **dashboard** card and a **prediction
  model** card — each button leads to *its own* app, and each card shows a live
  "available / not running" check of **its own address only**
  (‎`ANNE_DASHBOARD_URL`‎ / ‎`ANNE_ML_URL`‎; defaults ‎:8501‎/‎:8502‎).
  The target may be local or deployed in the cloud, and the check adapts to it:
  local — the TCP port + the identity of the process listening on it, and with it
  also the run command to copy; in the cloud — the HTTP response of the address
  itself, and with no local run command that does not lead there.
  Beside them the **project documents** grid (see below).
- **The document viewer 📄:** every document opens **inside the interface**,
  styled and branded — it is not downloaded to disk and does not open in external
  software. Alongside every document a small download button remains as a backup.
  One viewer with **a renderer per file type** (`server/documents.py` tags every
  document with a `kind`, and `web/admin.js` holds a registry under the same keys):
  - **The presentation and the progress board** (`html`) — displayed as they are
    in an iframe.
  - **The specification document, README, CLAUDE.md and the accessibility
    statement** (`markdown`) — converted to a branded HTML page (headings,
    tables, code blocks) in Anne's palette.
    **The specification document** is the definition of the system in 13
    chapters — problem and goal, scope, target users, functional and
    non-functional requirements, architecture, data model, constraints, safety
    boundaries, acceptance criteria and design decisions — and it is registered as
    an ordinary record in the closed list, with no special path and no new
    renderer.
  - **The system requirements** (`requirements`) — a card per package, grouped by
    purpose, with the rationale for every version pin.
  - **The test plan** (`checklist`) — not raw markdown but a visual checklist: a
    card for each of the 19 points with a status tag (✅ active · 🟡 partial ·
    ⏳ skipped) in the palette colors, a segmented progress bar at the top, and the
    skip reason shown on every point that is not active.
  - **The knowledge sources** (`sources`) — built **live from `data/`**: grouped
    by the four topics, and for every document a name, a link to the original
    source, a source-type tag (official medical / commercial / general guide —
    each in its own hue) and the option to open its four sections (symptoms ·
    first aid · continued care · immediate referral).
  - **The illustration storyboard** (`gallery`) — a live gallery from
    `illustrations/illustrations.json` with lazy loading of the images and the
    steps of every illustration.
  - **Demo scenarios** (`scenarios`) — a card per scenario with "what it
    demonstrates", the messages that will be sent and a run button. This is **the
    dedicated screen** for the scenarios; the board itself has only one entry card
    to it, and not another copy of the list.
  - **Licenses and rights** (`licenses`) — the view that answers the question "is
    there a package in the project that is not free to use?". The licenses are
    scanned **from the packages installed in the environment** on every open
    (`importlib.metadata` from the standard library — with no new dependency) and
    classified into four categories, each with its own colored tag:
    **permissive** (MIT · BSD · Apache-2.0 · ISC · PSF), **weak copyleft**
    (LGPL · MPL-2.0), **strong copyleft** (GPL · AGPL — a red flag) and
    **unrecognized / proprietary** (for manual review). In a combination of
    licenses the stricter one wins (`MPL-2.0 AND MIT` = weak), and what was not
    recognized is marked for review and not guessed. A package whose license is
    **not declared** in the metadata and was verified manually against the
    repository (currently `crewai` — MIT) is marked "manually verified" with a link
    to the license file that was verified; a declaration by the package itself
    always wins over such a verification.
    At the top a quantitative summary and a verdict in Hebrew; below it the content
    rights (the knowledge store in `data/` was rewritten on the basis of medical
    sources and is not a copy — with automatic verification that every document
    links to a source, and the illustrations and their rights status); and at the
    bottom a disclaimer: this is an automatic technical summary for documentation
    purposes and is not legal advice.

  **There are no embedded copies:** every document is read from its live source on
  every open, so an edit in the file appears in the display immediately. A missing
  file, an empty file or a corrupt catalog display an orderly Hebrew message — not
  a broken screen.
- **The demo scenario runner 🎬 (paid — it runs real turns):** the board has a
  single entry card to **the scenarios screen**, and in it a card per scenario.
  Clicking **"▶ run scenario"** opens the chat and runs it automatically — the
  lecturer types nothing:
  - Every message is **typed into the input field** (a short typing effect) and
    then sent, so that you see what is being written before it is sent.
  - The runner **waits for Anne's reply to finish** and then another ~3 seconds
    (with a countdown) before the next turn — time to read.
  - A sticky bar with **"turn 2 of 4"**, a progress bar and a **stop** button.
    Stopping halts the *scenario*; a turn that is already running on the server
    will finish (it has already cost money and been recorded in the log) — and the
    button says so.
  - At the end a **"the scenario has ended" card** is shown: which doctors handled
    it, which tools were invoked, which illustrations were displayed, whether
    Dexter stopped it (and on which red flags), how many turns were completed and
    how many LLM calls it cost — and all of it measured from the actual replies, not
    from what was expected. Beside it a **back to the admin area** button.

  **Five multi-turn scenarios** (3–4 turns each), which open with "hi, I have…"
  and develop gradually: a cut in the kitchen (Dr. Wynds), stress that builds into
  an anxiety attack (Dr. Anziety), a hot day in Tel Aviv (Dr. DeHydra — triggers
  weather and location), a cold (Dr. Colde), and a scenario that starts as the
  user's father's cold and worsens midway into chest pain and shortness of breath —
  where **Dexter stops the conversation**.

  **One source of truth:** `docs/demo_scenarios.json`. Both the cards and the
  messages that are sent are read from it live — an edit in the file changes the
  demo without touching the code and without restarting the server. **The scenarios
  are ordinary user input:** the runner types into the field and submits the form
  exactly like a person — they have no special path in the server, in the agents or
  in the log.
- **Access control — a single admin user:** access control for the admin area is
  based on a single admin user, whose details are kept in `.env` outside version
  control. This is a deliberate decision that matches the scope of the system — one
  actual user, and therefore there is no need for a user-management layer. The
  details are **not in the code** — they are read from the environment variables
  `ADMIN_EMAIL` and `ADMIN_PASSWORD` (in `.env.example` there is a placeholder
  only, because it goes up to Git), and the token that is returned sits in the
  process memory. **There is no default that permits login:** without the two
  variables the screen displays "לא הוגדרו פרטי כניסה" ("no credentials
  configured", 503) and it is impossible to log in at all — not even with empty
  fields. In keeping with that same scope, the admin area also does not protect any
  sensitive data: the document list is closed in the code — there is no `.env` and
  there are no log files.
  The input is normalized before the comparison (spaces, letter case in the
  address and invisible directionality characters that stick to a paste in an RTL
  page), and the comparison is done on bytes — otherwise `compare_digest` raises on
  a non-ASCII character, and the failure looks to the user like "wrong password".
  An authentication failure is always a 401, and every other state has a separate
  message with its status code.
- **Warm-up at server startup:** a background thread imports `crew` and loads the
  embedding model in advance. Measured in the log: the first turn in a cold process
  paid 25-50 extra seconds in the consult stage just for loading the model — the
  warm-up removes that.
- **One LLM call per structured stage:** in crewai 1.6.1 every stage with
  structured output paid a double call (a conversion stage that re-formats that
  same output). Today the schema is injected into the prompt and the reply is
  parsed in code — and if the parsing fails there is an automatic fallback to the
  previous conversion stage, so no path is worse than its predecessor.
  `structured_retries` in `TurnResult` reports how many fallbacks there were in
  the turn (0 = the fast path held).
- **Tests (offline, free):** the login gate (success/failure/logout), blocking all
  the admin routes without a token, the existence of every document in its place,
  serving from a closed list only (an unknown key or `../` → 404), and a single
  source display in `/api/chat` — all of it through `fastapi.testclient` inside the
  process, with no port and no LLM call.
  For every document the three states are checked (valid parse · missing file ·
  empty file); for the specification document it is additionally checked that the
  branded page really does contain its **tables and its code block** — meaning that
  the conversion to HTML did not lose those extensions.

### Vision layer — an image that enriches the intake (vision/) ✅ built and tested

An image can be attached to a message (the paperclip in the message composer), and
the system derives from it **context for the questioning — not a diagnosis**.
There is no new agent: the output is injected into the existing prompts exactly
like the time and weather context, and the decision stays with the specialist
doctor and with Dr. Dexter.

- **Three layers, Pillow + numpy only (no OpenCV):** (a) a quality check —
  sharpness (Laplacian variance **and also** the edge strength, because a smooth,
  sharp image looks to the first metric like a smeared image) and exposure;
  (b) deterministic measurements — the area of the *standout* red region relative
  to the image itself (skin in a warm hue is not a "finding"), the degree of its
  concentration, brightness and contrast; (c) a short verbal description from
  OpenAI's vision model, whose instruction forbids it from diagnosing, naming a
  disease, recommending treatment or grading severity.
- **A graceful fallback:** there is no key, there is no network, or the image did
  not pass the quality check — the description is simply not created, the
  measurements keep working and the conversation continues. `ANNE_VISION=0`
  disables the model call entirely.
- **Upload security:** the file type is determined by the content and not by the
  extension (JPEG/PNG/WebP only), there is a size and dimension limit that is
  checked before the decode, and the image is downscaled before processing.
- **Privacy:** the EXIF — which contains GPS coordinates and the device model —
  is removed before any processing; the image lives in the request's memory only
  and is not saved anywhere; and **only a single flag** is recorded in the log
  (`image_attached`, 0/1) — with no dimensions, no measurements and no
  description. From the value 1 nothing can be learned about the image, exactly as
  nothing can be learned from the message length about what was written in it.
- **A scope boundary:** if the description points at a subject outside the four
  topics (a mole, an eye injury, a nail, an unidentified rash) — the context
  carries an explicit instruction not to treat, but to say that this is out of
  scope and to recommend a doctor's examination. The image adds information, but it
  does not widen what Anne is qualified to treat.
- **Transparency:** Anne notes in her reply that the image was taken into account,
  and beneath the reply what was actually measured is displayed — including the
  sentence that the image is not a diagnosis and was not saved.
- **In the demo:** the "abrasion after a fall" scenario attaches a fixed demo
  image automatically (`assets/demo/`) and runs end-to-end with no intervention —
  through the same upload path as a real user (the same validation, the same EXIF
  removal). The image was AI-generated for the project and is declared on the
  licenses page. The user's "await image" step remains supported for scenarios in
  which one wants to show a live upload.
- **Cost:** one call to the vision model at the default (gpt-4o-mini,
  `detail: "low"`) is about 3,100 input tokens and 150 output tokens ≈ **$0.0006
  per image** (less than an agora). `ANNE_VISION_MODEL` allows swapping the model.

### Personal credit and branding ✅

The line **"Built by Maor Dahan as part of an AI course from the School of
Business Administration of the Hebrew University"** appears on all the project's
screens: the chat, the three views of the admin area (login, board and the
document viewer — and from it also the demo scenarios screen, the gallery and the
licenses), the branded document pages, the public accessibility statement and both
Streamlit apps.

- **One source of truth:** `credit.py` defines the text, the links, the aria
  labels and the icons; `web/credit.js` mirrors it to the browser (a static page
  cannot read Python, and reading a JSON would have added a network request), and
  an offline check compares the nine fields string by string — any drift brings the
  suite down.
- **The links:** the name and the LinkedIn icon → the profile; the GitHub icon →
  the repo. All of them `target="_blank"` with `rel="noopener noreferrer"`.
- **Accessibility:** a Hebrew `aria-label` for every icon, the SVG `aria-hidden`
  so that it is not read twice, a 44×44 click area (measured in the browser) and
  visible keyboard focus.
- **Offline and print:** inline SVG — no CDN, no icon font and not a single
  network request; and on the document pages the line remains visible in print too.

### Accessibility — WCAG 2.1 level AA ✅

This is a medical application, and therefore accessibility is part of the job and
not an accessory. The target: **WCAG 2.1 level AA** — the common denominator of
**SI 5568 part 1** (September 2023, which is WCAG 2.0 with national changes) and
of the European **EN 301 549** (WCAG 2.1 AA). Level AAA is **not** a target. The
two Israeli changes that are relevant here were taken from the standard itself:
**2.4.10** (section headings) was raised to AA — the headings are real `h` tags;
and **3.1.2** (language of parts) **does not apply**, and therefore there are no
`lang` wrappers around foreign terms.

- **Structure and navigation:** `lang="he"`/`dir="rtl"`, landmarks
  (`header`/`nav`/`main`/`footer`), a heading hierarchy with no level skips, and a
  **"skip to content" link** first in the tab order. Every action is available from
  the keyboard, with a visible focus ring; Escape closes panels and returns the
  focus.
- **The chat — three announcement regions, on purpose:** the conversation log is a
  `role="log"` with `aria-live="polite"` (a reply is announced **when it is
  complete**); the stage labels ("consulting with the medical team…") are in a
  separate `role="status"` region; and **an emergency message from Dr. Dexter is
  announced immediately** in a `role="alert"` region (assertive) that interrupts
  the reading — including "call 101". While the reply is streaming the bubble is
  hidden from the screen reader until it is complete, so that not every chunk is
  announced separately.
- **Images:** the treatment illustrations have alt text that **describes the
  steps** ("guided illustration — cleaning and disinfecting a cut. The steps
  demonstrated: …"), not "illustration"; figures and decorations with `alt=""`. The
  demo indicator is a `role="progressbar"` with "turn 2 of 4".
- **Contrast:** the palette tokens were measured and fixed to 4.5:1 for text and
  3:1 for control borders — the secondary text went up from 4.25 to 5.16, the links
  from 3.72 to 5.33, and the primary button (white text) from 2.48 to 5.33. An
  automatic check scans every `color: var(--…)` in the stylesheets and fails a token
  that does not meet the ratio.
- **An accessibility panel:** a fixed button in the corner (keyboard accessible)
  opens a panel with text enlargement/reduction (up to 160%), a high-contrast mode,
  reduced animations and focus emphasis. The preferences are saved in the browser
  only; the system also respects `prefers-reduced-motion`.
- **An accessibility statement** at the public route **`/accessibility`** (and
  also in the admin area's viewer, from the same live file). It is worded as an
  **aspiration** to WCAG 2.1 AA and not as a legal conformance claim — this is an
  educational project — and it details explicitly **what is not covered** (not
  tested with real screen readers, the Streamlit apps, the document files).
- **Tests:** 8 offline checks (`alt` on every image, an accessible name for every
  icon button, a `label` for every field, the `aria-live` regions, the contrast
  ratios, structure and headings, the keyboard, and the panel and the statement).
  What cannot be derived from the code — tab order, the panel's behavior,
  `aria-hidden` during streaming, and the absence of horizontal scrolling at a
  320px width — was verified by rendering in headless Chrome.

## Running

```bash
# 1. Installing dependencies (prefer prebuilt wheels, avoid local compilation)
python -m pip install --prefer-binary -r llm_requirements.txt

# 2. Building the Vector DB (on the first run the embedding model, ~2GB, is downloaded)
python build_index.py

# 3. A preview of the chunks without embeddings (fast, for inspecting the chunking)
python -m rag.chunking

# 3b. Filling in coordinates for the emergency destinations — one-off, only when
#     adding/changing records in data/emergency_locations.json. It uses the
#     existing geocoding tool (tools/location.py, Open-Meteo, no key), one query
#     per locality, and skips records that already have coordinates.
#     During a conversation there is no network call at all — this is the only way
#     they enter the file.
python geocode_emergency_locations.py             # actually filling them in
python geocode_emergency_locations.py --dry-run   # printing only
python geocode_emergency_locations.py --force     # re-geocoding all of them

# 4. Setting the API key (mandatory for the agents stage)
cp .env.example .env    # and fill in OPENAI_API_KEY,
#                         and ADMIN_EMAIL/ADMIN_PASSWORD for the admin area

# 5. An interactive conversation with Anne (performs paid LLM calls)
python -m crew.main

# 6. The test suite — every check is mapped to a presentation slide, and the summary is printed per slide
python test_anne_suite.py            # 10 live scenarios (paid LLM calls!)
python test_anne_suite.py 5          # a single scenario by number
python test_anne_suite.py --list     # the scenario list only, with no LLM calls
python test_anne_suite.py --offline  # offline checks — free, no LLM
                                     # (including the log layer checks: schema, scrub,
                                     #  the CHECK guard, reset and the wiring to the pipeline,
                                     #  and the prediction model: training, save/load and prediction)

# 7. Synthetic data for the conversation log (free, no LLM) — for the dashboard/prediction model.
#    Written to a separate file (anne_log_synthetic.db) through the same scrub+CHECK path;
#    the same seed produces the same data (--reset clears before a repeat write)
python -m storage.synthetic --rows 500 --seed 42
#    Under ANNE_LOG_BACKEND=supabase the same command seeds the turns_synthetic table
#    (or explicitly: --db turns_synthetic), and prints the actual target at the end.

# 7b. Supabase (optional) — one-off, before switching to ANNE_LOG_BACKEND=supabase:
#     run storage/migrations/001_create_turns.sql in Supabase's SQL Editor
#     (it creates turns and turns_synthetic, enables RLS and blocks anon).
#     The script is idempotent; it is generated from the schema and can be rebuilt:
python -m storage.pg_schema --write      # free, no network

# 8. The two Streamlit apps over the log (free, no LLM; local servers).
#    Each one runs in its own terminal and on its own port, and only one of them can be run.
streamlit run dashboard/app.py --server.port 8501     # overview → :8501
streamlit run dashboard/ml_app.py --server.port 8502  # prediction → :8502
#    app.py    — KPIs, trend, breakdowns, table/CSV + the log reset button with double confirmation
#    ml_app.py — the educational prediction model page (model cards, mathematics, what-if)

# 9. The prediction models (free, no LLM) — an educational demonstration only, not a clinical tool.
#    Training four models on the same split + a comparison table, saving to ml/models/,
#    and then a demo that runs all the models on sample records
python -m ml.train
python -m ml.train --model random_forest   # which one will be the default in the bundle
python -m ml.predict

# 10. The browser interface + the admin area (the server itself is free; a user message triggers
#     paid LLM calls through that same pipeline)
python -m uvicorn server.app:app --port 8000
#     and then open http://localhost:8000
#     Diagnostics (local, off by default): ANNE_DIAG=1 prints, for every turn, which
#     tools were invoked and what they returned, the context strings as they were
#     injected into the specialist doctor, and the history length at the start and end of the turn
#       /       — the chat with Anne
#       /admin  — the admin area (a single admin user: ADMIN_EMAIL / ADMIN_PASSWORD
#                 from the .env environment file — without them there is no login)
#     Optional: ANNE_DASHBOARD_URL / ANNE_ML_URL — the two addresses the admin
#     area links to and checks the availability of, each one separately. The default
#     is local (‎http://localhost:8501‎ / ‎http://localhost:8502‎); when they
#     point at apps deployed in the cloud, the check moves from a port check to a check
#     of the HTTP response of the address itself (see below)
```

> A demo tip: so that both buttons in the admin area show "available", run the two
> apps in two additional terminals:
> `streamlit run dashboard/app.py --server.port 8501` and
> `streamlit run dashboard/ml_app.py --server.port 8502`.
> Each button checks *its own* port, so "not running" on one says nothing about the
> other.
>
> When the apps are **deployed in the cloud** and `ANNE_DASHBOARD_URL`/`ANNE_ML_URL`
> point at them, there is nothing to run in a terminal — and the check switches
> method: a TCP check would have shown "available" always, because all Streamlit
> Cloud apps share one host and therefore port 443 is open even for the name of an
> app that is not deployed (measured). Therefore on a remote target the HTTP
> response of the address itself decides: a deployed app returns 200 (even when it
> is "asleep" — the link wakes it), a name that is not deployed returns 404 and is
> displayed as "address not found", an app protected by the hosting service's login
> gate is identified by the redirect that **leaves its own host** and is displayed as
> "requires sign-in", and a network failure is displayed as "not reachable". Four
> separate messages, because each demands a different action — and the third one
> especially: a login gate redirects every path (the health check included) and ends
> at the login screen's 200, so swallowing redirects would have declared "available"
> for an app no visitor can open (measured on both deployed apps). A local run
> command is not offered on a cloud card: it brings up an app at localhost, which is
> not the address the button opens.

Semantic retrieval run programmatically:

```python
from rag.embedding_store import search

results = search("איך מטפלים בחתך?", top_k=4, topic="wounds")
for r in results:
    print(r)
```

A programmatic conversation (for example for a future interface connection):

```python
from crew import ChatSession

session = ChatSession()
result = session.run_turn("נחתכתי בסכין, דימום קל")
print(result.reply_he)          # Anne's reply
print(result.illustration_id)   # a validated illustration from the closed list, or None
print(result.sources)           # the sources cited
```

## Version control

The project is managed in Git and stored in a **private** repo on GitHub. Two
branches, and that is the whole process:

| Branch | Role |
| --- | --- |
| `main` | The stable branch — what is presented and demoed. Only what works is merged into it. |
| `dev` | The development branch — this is where the work and the routine commits happen. |

```bash
git switch dev                 # develop here
git add -A && git commit -m "…"
git push

git switch main                # when the feature is stable
git merge dev
git push
```

### Running after clone

Cloning the repo is not enough in order to run it: three artifacts are
deliberately **not** in version control — the API keys (`.env`), the Vector DB
(`chroma_db/`, ~built locally), the log files (`anne_log*.db`) and the prediction
models (`ml/models/`). Therefore, after a clone:

```bash
git clone https://github.com/maordahan25/anne-triage-assistant.git
cd anne-triage-assistant

# 1. Dependencies (the file name is llm_requirements.txt, not requirements.txt)
python -m pip install --prefer-binary -r llm_requirements.txt

# 2. Environment variables — create .env from the template and fill in a real key
cp .env.example .env
#    OPENAI_API_KEY — mandatory for the agents stage
#    ADMIN_EMAIL / ADMIN_PASSWORD — for the admin area (without them there is no login)
#    ANNE_LOG_BACKEND — sqlite (the default) or supabase; supabase also requires
#    SUPABASE_DB_URL, and without it the log falls back gracefully to SQLite with a warning

# 3. Building the Vector DB — mandatory, because chroma_db/ is not in version control.
#    On the first run the embedding model (~2GB) is downloaded.
python build_index.py

# 4. A free verification that everything is in place (with no LLM calls)
python test_anne_suite.py --offline
```

The data for the dashboard and for the prediction model is also built locally, and
only if it is needed:
`python -m storage.synthetic --rows 500 --seed 42` and then `python -m ml.train`.

## Environment notes

- Tested on **Python 3.12** (the conda environment `anne_env`).
- **`numpy<2` is a hard constraint:** the `torch` available for macOS/x86_64 is
  built against NumPy 1.x; NumPy 2 breaks it. `crewai` is pinned to `1.6.1` so as
  not to pull in `numpy>=2`. See the rationale comments in
  `llm_requirements.txt` before changing the pins.
- `.env` files, the `chroma_db/` directory and the `anne_log*.db` log files are not
  in version control (see `.gitignore`).

## Next steps

- **Response time — what is left** — done: the RAG warm-up at server startup, one
  call per structured stage, and streaming the phrasing. What is still outstanding:
  the hierarchical crew path (`other`), which was measured at 231 seconds and 30
  calls, and skipping the safety gate/triage on greetings (deterministic detection
  already exists, but it runs after the two LLM calls).
- Deepening the prediction model (`ml/`) with real data: probability calibration,
  additional features and model comparison — the educational demonstration is
  already built.
- Automatic quality control in the RAGAS style and polishing security/privacy.
