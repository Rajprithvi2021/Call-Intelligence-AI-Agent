# Call Intelligence Agent (v0)

Turns a call or meeting (audio or transcript) into notes a person can rely on:
summary, decisions, action items (owner and due date), blockers, compliance
observations (RED/YELLOW/GREEN), sentiment, risk flags, and a **human-review queue**.
**Every item points to the exact transcript lines it came from.** The code copies
those lines from the original text, so the model can't reword them.

```
audio / transcript
  1  Transcribe (Gemini, diarized segments)                         app/stt.py
  2  Numbered lines  [n] Speaker: text                              app/transcript.py
  3  Rule pre-scan: stop-contact, legal, bankruptcy, wrong number,  app/rules.py
     PII, profanity, anger, recording disclosure
  4  ANALYST agent: transcript + policy KB + rule hints -> draft    app/agents/analyst.py
  5  Grounding (code): line numbers checked, quotes copied          app/grounding.py
     verbatim, dates computed from the meeting date                 app/dates.py
  6  REVIEWER agent (LLM-as-judge): sees only transcript + claims   app/agents/reviewer.py
  7  Escalation policy (code): decides what a human must check      app/escalation.py
  8  Store + index (keyword + semantic search)                      app/store.py, app/db.py
```

The LLM decides *what happened*. Code enforces *proof and policy*:
- A claim with no valid transcript line is **not asserted**; it goes to review.
- Dates are resolved by code ("Friday" said on Wed 2026-07-01 becomes 2026-07-03, "the 15th of next month" becomes 2026-08-15). A vague deadline, or a disagreement between the model and the resolver, goes to review.
- High-stakes phrases ("I told you guys not to call", "contact my attorney", "I am bankrupt", "wrong number") are caught by rules even if the model misses them. The same phrases are ignored when the agent says them.
- The judge can remove unsupported items and add review items. It can never cancel a rule-based escalation.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
copy .env.example .env            # then set GEMINI_API_KEY
```

Process one transcript from the command line (prints grounded JSON):

```bash
python -m app.pipeline data/samples/debt_collection_2026-07-01.txt --date 2026-07-01 --domain debt_collection
```

Run the API and the UI (two terminals):

```bash
uvicorn app.api:app --port 8000
streamlit run ui/streamlit_app.py
```

Open http://localhost:8501. Pick a sample on the **Process call** page (or upload
audio or a `.txt`), then open it under **Calls**. You can also work through the
**Review queue** and **Search**. API docs are at http://localhost:8000/docs.

A two-speaker test recording is in `data/samples/audio/`. To generate more:
`python scripts/make_sample_audio.py <transcript.txt> <out.wav>`

### Storage

- `DATABASE_URL` empty: a local JSON store in `data/store/` (dev only, zero setup).
- **Postgres + pgvector** (recommended): `docker compose up -d` with
  `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/callintel`, or a free
  Neon/Supabase database (`...?sslmode=require`). Tables are created on startup
  (`db/init.sql`).

The driver is `pg8000` (pure Python), because this machine's application-control
policy blocks the compiled `psycopg` DLLs.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/calls` | multipart: `meeting_date`, `file` (audio/.txt) **or** `transcript`, optional `title`, `domain`, `participants`. Processes in the background. |
| GET | `/calls`, `/calls/{id}` | list, or notes + transcript + review items |
| POST | `/calls/{id}/retry` | re-run a failed call from its stored input |
| GET | `/review?status=open` | human-review queue |
| POST | `/review/{id}` | `{"status": "approved" \| "rejected" \| "edited", "resolver", "note"}` |
| GET | `/search?q=&domain=&flag=&sentiment=` | hybrid keyword + semantic search over transcript lines |
| GET | `/health` | active models and store |

Call status moves through `queued → analyzing → reviewing → indexing → done`
(`transcribing` first for audio). A failure ends in `failed` with the error message.

## Output (per call)

`CallNotes` in `app/schemas.py`: `tag`, `summary`, `domain`, `speaker_roles`,
`decisions[]`, `action_items[]` (owner, owner_role, start/due date, due phrase,
date_status, date_note), `blockers[]`, `next_steps[]` (proposals, not commitments),
`compliance[]` (rule_id, RED/YELLOW/GREEN), `sentiment` (overall, customer_angry,
profanity), `risk_flags[]` (cease_and_desist, legal, bankruptcy, wrong_number, pii,
consent_refused/unclear), `review_items[]`, `overall_confidence`, and the `models` used.
Every item carries `evidence: [{line, speaker, text}]` and, when judged, a
`judgement: {verdict, confidence, reason}`.

### When something goes to a human (`app/escalation.py`)

- no clear owner, a vague deadline, or a model/resolver date disagreement
- confidence below `REVIEW_THRESHOLD` (0.7), or the judge says `unsupported` / `needs_human`
- a claim with no valid evidence (held back, not asserted)
- a RED compliance finding, or any risk flag (stop contact, legal, bankruptcy, wrong party, PII, recording consent)
- a customer-facing call with no recording disclosure
- anything needing authority: approvals, settlements, splits, refunds, discounts, waivers, exceptions
- customer anger or profanity (for coaching)
- anything else the Analyst or the judge flags. The list is open-ended.

## Knowledge base

`policies/*.md` holds `general`, `debt_collection`, `sales`, `support` and `standup`
rules, each with a `rule_id`. v0 puts the whole policy file for the domain into the
prompt, or all files when the domain is unknown. Edit these files to change what is checked.

## Tech stack and trade-offs

| Layer | Choice | Why | Trade-off |
|---|---|---|---|
| LLM (all agents) | Gemini `gemini-3.6-flash` via `google-genai` | One key covers transcription, reasoning and embeddings. Native JSON-schema output. Long context. | Flash reasons less deeply than Pro, which is why grounding and escalation live in code. Same model for Analyst and judge means correlated errors, reduced by giving the judge only the transcript and the claims. |
| Transcription | Gemini audio understanding, behind a `Transcriber` interface | No second vendor or key | Timestamps are approximate and speaker labels can drift. `DeepgramTranscriber` (Nova-3) is included for production diarization (`TRANSCRIPTION_PROVIDER=deepgram`, untested in v0). |
| Orchestration | Plain Python pipeline | The flow is fixed, so it stays deterministic and testable | No agent framework features. Not needed yet. |
| Knowledge base | Full policy file in the prompt | Can't miss a rule; files are small | Doesn't scale. v1 retrieves from `kb_chunks` (table already exists). |
| Rules | Regex lexicons | Guaranteed recall on high-stakes phrases, with line refs | Misses paraphrases (the LLM covers those). False positives cost one reviewer click. |
| Dates | `dateutil` + custom resolver | Exact, testable | Only common phrases. The rest are marked vague and reviewed. |
| Storage/search | Postgres + pgvector (FTS + cosine, RRF merge) | One store for records, JSON, keyword and vector search | Needs a server. The local JSON store bridges the gap for dev. |
| API/jobs | FastAPI + `BackgroundTasks`, one job at a time | No extra infrastructure | Jobs don't survive restarts (they're marked failed and can be retried). v1: a queue (Arq/Celery). |
| UI | Streamlit | Fastest usable internal tool | Not customer-grade. |

### Gemini free tier

The free tier allows **20 requests per day per model**, and each call uses 2 (Analyst
and Reviewer). When a model returns 429 or 503, the pipeline moves on to the next
model in `LLM_FALLBACK_MODELS` and records which model answered in `notes.models`.
It does not keep retrying a model whose daily quota is spent. For real volume,
enable billing on the Google AI project.

## Tests and eval

```bash
pytest                                   # offline: dates, rules, grounding, escalation, golden pipeline (stubbed LLM)
python scripts/eval_spec_example.py --runs 3   # live: pass rate of the spec example's expected outputs
```

## Roadmap (v1+)

A job queue and object storage for audio; authentication and reviewer roles; KB
retrieval; dedicated STT (Deepgram: diarization, redaction, multichannel); a
Pro-tier Analyst or a different-vendor judge; a labeled eval set with per-field
precision and recall; feeding reviewer decisions back into prompts and rules; Batch
API for backfills; tracing and cost dashboards; a React front end; real-time calls.
