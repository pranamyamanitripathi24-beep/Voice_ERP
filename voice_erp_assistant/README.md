# AI Voice-Controlled ERP Assistant — Working Prototype

Implements the architecture from the project slides: **User Interface Layer →
AI Processing Layer → Integration Layer → ERP Core**, with the 7-stage
pipeline (Voice/Text → STT → NLU → Dialog Manager → API Gateway → ERP →
TTS/Response).

## What's included

| File | Slide it implements |
|---|---|
| `app/database.py` | ERP Core — SQLite inventory, people, sales, procurement, and expense data |
| `app/nlu.py` + `app/intents.py` | AI Processing Layer — intent classification + entity extraction |
| `app/entity_resolver.py` | Fuzzy name matching — lets you say item/employee names instead of exact codes |
| `app/dialog_manager.py` | Dialog Manager — clarification loop, write-confirmation, misheard-entity confirmation |
| `app/erp_gateway.py` | Integration Layer — API Gateway, RBAC hook, response formatting |
| `app/reporting.py` | CSV and PDF sales report generation |
| `app/stt.py` | Offline Vosk speech-to-text + audio preprocessing |
| `app/tts.py` | Text-to-Speech (pyttsx3, offline) |
| `app/main.py` | FastAPI server — serves the website below plus `/voice/text` and `/voice/audio` |
| `static/index.html` + `style.css` + `app.js` | The website — User Interface Layer, slide 3/7 |
| `demo.py` | Standalone script, runs all use cases with zero setup |

This has been tested end-to-end and works out of the box for text input —
no API keys needed to see the whole pipeline run.

## ERP workflows

The seeded SQLite ERP includes suppliers, purchase requests and line items,
expenses, and product-linked sales. Existing databases are upgraded
automatically when the app starts.

- **Procurement:** “Which items are low in stock?” lists items at their
  reorder threshold. “Create a purchase request for hydraulic valves” asks
  for a quantity, previews the supplier and estimated total, then requires
  confirmation before saving the request.
- **Expenses:** “How much did we spend this month?”, “What was our total
  expenditure last month?”, and “Show me the highest expenses” query the
  expense ledger.
- **Reports:** “Generate this month's sales report” summarizes sales,
  transaction count, top product, prior-period total, and percentage change.
  Finance/admin/demo users can download a CSV or PDF in the workspace, or
  call `/reports/sales?period=this_month&format=csv` (use `format=pdf` for PDF).
  Amounts are reported in INR.

## Step-by-step: getting it running

1. **Install core dependencies**
   ```bash
   pip install -r requirements.txt
   ```
  `reportlab` generates PDF exports; the CSV exporter uses Python's standard library.

2. **Run the zero-setup text demo first** (proves the whole pipeline works,
   no mic/API keys required):
   ```bash
   python demo.py
   ```
   This runs the 3 scenarios from slide 9 (inventory query, attendance
   logging with confirmation, sales report), then drops you into an
   interactive prompt.

3. **Run the server, and open the website:**
   ```bash
   uvicorn app.main:app --reload
   ```
   Open **http://127.0.0.1:8000/** in a browser — that's the website
   (`static/index.html`), a chat-style UI you can type or speak into
   directly, talking to the exact same backend as `demo.py`.
   `http://127.0.0.1:8000/docs` still gives you the raw Swagger API if
   you want to test endpoints individually:
   ```bash
   curl -c cookies.txt -X POST http://127.0.0.1:8000/auth/demo
   curl -b cookies.txt -X POST http://127.0.0.1:8000/voice/text \
     -H "Content-Type: application/json" \
     -d '{"session_id": "demo1", "text": "Show stock for item P-102"}'
   ```

4. **Add local voice input/output** for the website's Record button
   (optional, once the text pipeline is proven):
   - Vosk is the project's primary and only STT engine. Install it with
     `pip install vosk`; no speech API or API key is used.
   - Download a model from https://alphacephei.com/vosk/models and extract
     it to `models/vosk-model-small-en-us-0.15`, or set `VOSK_MODEL_PATH`
     to the extracted model directory.
   - Install `ffmpeg` and make sure it is on PATH for audio conversion.
   - Install `pyttsx3` for local text-to-speech. With the app, Vosk model,
     and TTS running on your machine, voice processing stays local.
   - `POST /voice/audio` accepts audio and returns a synthesized `.wav`
     reply with `X-Transcript` / `X-Reply-Text` headers.

5. **The website is already built** (slide 7's "Frontend" requirement) —
   `static/index.html`, `style.css` and `app.js`. It's plain HTML/CSS/JS,
   no build step, no npm — open http://127.0.0.1:8000/ once the server
   is running. See "How the website connects to the backend" below for
   how it works and how to customize it.

6. **Swap the mock ERP for a real one** (when ready):
   - Replace the function bodies in `app/database.py` with calls to
     Odoo's XML-RPC API (`odoorpc` or `xmlrpc.client`) or your real
     Postgres schema. Keep the same function signatures
     (`get_stock`, `mark_attendance`, `get_sales_report`, `update_stock`)
     — nothing else in the app needs to change.

7. **Upgrade the NLU** (when the rule-based version isn't enough):
   - Replace `app/nlu.py`'s `classify()` with a Rasa model call, or a
     LangChain + GPT call prompted to return `{"intent": ..., "entities": {...}}`
     JSON. Keep the `NLUResult` return shape and everything downstream
     (Dialog Manager, Gateway) is untouched.

8. **Harden security** (slide 6 & 8):
   - Replace the placeholder `role="admin"` default in `erp_gateway.dispatch()`
     with a real OAuth2/JWT-derived role from the authenticated session.
   - Add API-key auth on the FastAPI routes (`fastapi.security`).
   - Add rate limiting / caching for frequently-hit read endpoints
     (slide 8: "High latency" mitigation).

9. **Deploy** (slide 7): containerize with Docker, run behind
   `uvicorn`/`gunicorn` on a local server or AWS/GCP (ECS, Cloud Run, etc.).

## Is it actually AI? (important — read this)

`app/nlu.py` is **regex pattern matching**, not AI. It's `if command ==
"check attendance"` wearing a nicer outfit — fast, free, zero setup, but
it only understands sentences that match a pattern someone wrote in
advance. Ask it "Am I eligible for exams based on attendance?" and it
fails, because no one wrote a pattern for that exact shape of sentence.

`app/nlu_llm.py` is the real fix. It sends your sentence to a small
language model (running locally via **Ollama** — free, offline, no API
key) and asks it to figure out the intent and entities itself. The model
has actually learned language, so it correctly maps *"How much
attendance do I have"*, *"Show my attendance for this semester"*, and
*"What's my attendance like"* all to the same `get_attendance_summary`
intent — no one had to predict those exact words.

**To turn it on:**
1. Install Ollama: https://ollama.com (free, one-click installer)
2. `ollama pull llama3.2:1b` (≈1.3GB, one-time download, runs on CPU)
3. `export NLU_ENGINE=llm` (Mac/Linux) or `set NLU_ENGINE=llm` (Windows)
4. Run `python demo.py` or `uvicorn app.main:app --reload` as normal

If Ollama isn't running, `nlu_llm.py` catches the connection error and
falls back to the regex engine automatically — it won't crash your app,
it'll just quietly lose the flexibility until Ollama is running again.

### "The commands are only attendance and P102 — what about anything else?"

Two separate things are going on here, and they scale differently:

- **Entity values** (which item, which employee) already generalize.
  `_ITEM_ID_RE` in `app/nlu.py` matches *any* code shaped like
  `P-102`, `X-9`, `M-4501`, etc. — it was never hardcoded to P-102
  specifically. Try `check stock for P-999` in the demo; it correctly
  says "no item found," proving it's reading the pattern, not a fixed
  string. Same for `E-001` — any `E-###` employee ID works.

- **Intents** (what kind of question) are what's limited — the rule
  engine only recognizes the shapes of sentences you write a pattern
  for. This is the part `nlu_llm.py` fixes, and it's also the part you
  extend as your project grows. **Adding a new command is a 3-file
  change**, whichever NLU engine you're using:
  1. `app/intents.py` — add the intent name, its required entities, and
     whether it's a write operation.
  2. `app/database.py` — add the actual database query/logic function.
  3. `app/erp_gateway.py` — add one `if intent == "...":` branch in
     `dispatch()` (call the DB function) and one in `format_reply()`
     (turn the result into a sentence).

  With the **rule-based** engine you'd also add regex patterns to
  `app/nlu.py` for every phrasing you want recognized — this is the
  part that doesn't scale, since you're back to predicting sentences.
  With the **LLM** engine, step 4 is just adding one example line to
  the `SYSTEM_PROMPT` in `nlu_llm.py` — the model generalizes the rest.

  `get_attendance_summary` and `check_exam_eligibility` were added to
  this project exactly this way — see the diffs in `intents.py`,
  `database.py`, and `erp_gateway.py` for a worked example.

## Improving voice accuracy

If transcription accuracy feels poor, it's very rarely "your voice" — it's
usually one of three fixable things, all addressed in this codebase:

**1. Audio format.** Your laptop/phone mic often records at 44.1kHz or
48kHz stereo; STT engines expect 16kHz mono. Feeding the wrong format in
doesn't error out — it just quietly produces worse transcriptions with no
warning. `app/stt.py`'s `preprocess_audio()` fixes this with one ffmpeg
call, and `/voice/audio` in `app/main.py` already runs it automatically
before every transcription. Make sure ffmpeg is installed and on PATH
(`ffmpeg -version` to check).

**2. Alphanumeric codes are hard for any STT engine.** "P-102" spoken
aloud gives the model almost no acoustic signal to distinguish it from
"P-100" or "P-192" — speech recognition generally struggles with short
alphanumeric codes. The fix isn't a better
model, it's not requiring codes at all: `app/entity_resolver.py` lets you
say the item or employee's actual *name* instead — "check stock on the
hydraulic valve" or "mark attendance for Asha Rao" both work now, even
with minor mishearing, via fuzzy string matching against the real
database records.

**3. A safety net for genuine mishearing.** When a name is only a
partial or shaky match (STT garbled it more than usual), the assistant
now asks "I think I heard X — is that right?" before acting, instead of
silently guessing. Try it: say something deliberately mangled like
"check stock for hydrolick valv" — you'll get a confirmation prompt
instead of a wrong answer. This is real code in `dialog_manager.py`
(`_advance_uncertain_or_continue`), not just documentation — it runs on
every request, from both the rule-based and LLM-based NLU engines.

**Further improvements you can make, roughly in order of effort:**

| Change | Effort | Impact |
|---|---|---|
| Use a larger Vosk model from the supported model list | Change the model path | Large — general accuracy across all speech, not just codes |
| Record in a quiet room, 6–12 inches from the mic | None (just habit) | Medium — background noise is the #2 real-world cause of bad STT |
| Use a USB/headset mic instead of a laptop's built-in mic | Buy a $15–20 mic | Medium |
| Vosk "grammar" mode — constrain recognition to only the words this app actually uses (item names, "stock", "attendance", numbers) | A few hours | Large for this specific use case, since the vocabulary is small and known in advance — see Vosk's `SetGrammar` in their docs |
| Prompt the user with example phrasing ("try: 'check stock on...'") in the UI | Trivial | Small but real — reduces genuinely out-of-scope phrasing |

## How the website connects to the backend

This is the part worth understanding, since it's the same pattern every
real web app uses:

1. `app/main.py` runs a web server on your laptop at `127.0.0.1:8000`.
   `app.mount("/static", ...)` tells it to hand out `style.css` and
   `app.js` as plain files; `@app.get("/")` tells it to hand out
   `index.html` when you visit the root address.
2. Your browser loads `index.html`, which loads `app.js`.
3. When you click Send, `app.js` calls `fetch("/voice/text", {...})` —
   this is a plain HTTP POST request, the exact same kind of request
   Postman or `curl` sends, just made from JavaScript instead. `fetch()`
   is the standard way any website talks to any backend.
4. FastAPI receives that request at the `/voice/text` route in
   `app/main.py`, runs it through `dialog_manager.py` exactly like
   `demo.py` does, and sends a JSON reply back.
5. `app.js` reads that JSON and adds a new chat bubble to the page.

The Record button follows the same pattern but with audio: the browser's
built-in `MediaRecorder` API captures microphone audio into a file in
memory, `app.js` POSTs it to `/voice/audio`, and gets back either a
`.wav` file to play (full voice pipeline) or a JSON error explaining
what's missing (e.g. "install pyttsx3") if you haven't set up STT/TTS
yet — see step 4 above.

Because the website and the API are served from the same address
(`127.0.0.1:8000`), the browser treats them as one thing and doesn't
apply CORS restrictions — the security rule that normally blocks a
website from calling an API hosted somewhere else. If you ever split
them (host the website separately, e.g. on Vercel/Netlify, calling an
API on a different server), you'd need to add
`from fastapi.middleware.cors import CORSMiddleware` to `main.py` — not
needed for local development like this.

## Extending to the "Future Scope" items (slide 10)

- **Multilingual:** Vosk provides language-specific models; choose the
  appropriate local model and localize `CLARIFY_PROMPTS` / reply templates
  in `dialog_manager.py` and `erp_gateway.py`.
- **Offline:** voice transcription uses Vosk locally. Pair it with the
  rule-based NLU or a locally hosted small NLU model for a fully offline
  voice pipeline.
- **Proactive alerts:** add a background job (e.g. APScheduler or a cron)
  that polls `database.get_stock()` against `reorder_threshold` and pushes
  a TTS-rendered alert through a websocket or push notification.

## Operations dashboard, inventory, and history

The website now shows inventory totals, reorder alerts, monthly sales (for
finance/admin roles), and the signed-in employee's attendance summary. The
inventory browser can search by product name or ID, filter to items at or
below their reorder threshold, and open a stock query from an item row.
Conversation history is stored in the current browser's local storage and
survives refreshes; use **Clear history** on shared devices.

## Optional sign-in and roles

The project still starts in its original demo mode unless
`ERP_AUTH_ENABLED` is set. To enable sign-in, generate a salted PBKDF2
password record for each existing employee ID (the password is read without
echo):

```powershell
python -c "import json; from getpass import getpass; from app.auth import password_record; print(json.dumps({'E-003': password_record(getpass())}))"
```

Copy the printed JSON into `ERP_AUTH_USERS`, replacing the example record
with the generated value. Add one entry per account. For example, `E-001`
is a field worker, `E-002` is finance, and `E-003` is admin in the seeded
database:

```powershell
$env:ERP_AUTH_USERS = '{"E-003":"<generated salt$hash>"}'
$env:ERP_AUTH_ENABLED = "1"
uvicorn app.main:app --reload
```

The website always opens at the sign-in screen. With auth enabled, employee
sign-in is required and the demo entry is disabled. With auth unset, the
screen offers a separate demo-workspace button; protected ERP and voice
routes still require its short-lived HttpOnly session cookie. API clients
should retain and resend the `erp_session` cookie from `/auth/login` or
`/auth/demo`. Roles come from the employee table: admins can use all
features, finance can view sales, and field workers can access inventory
and only their own attendance. Set `ERP_COOKIE_SECURE=1` when serving over
HTTPS. Set `ERP_DEMO_ENABLED=0` to disable local demo entry.

This authentication is suitable for a local prototype, not production:
users and sessions are configured/in-memory, sessions are lost on restart,
and multiple server workers do not share sessions. Use an established
identity provider and shared session store before connecting real ERP data.
Keep `ERP_AUTH_ENABLED` set for employee sign-in; for local demo evaluation,
leave it unset and enter through the explicit demo-workspace option.
