# BriefTune — Developer Workflow

## Every Time You Open This Project

1. Open VS Code — it will remember the `brieftune` workspace automatically
2. Press `Ctrl+`` ` `` to open the terminal
3. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```
4. Start the Flask server:
   ```bash
   python3 run.py
   ```
5. Wait for this to appear in the terminal:
   ```
   * Running on http://127.0.0.1:5000
   ```
6. Open the app: `Cmd+Shift+P` → `Simple Browser: Show` → `http://127.0.0.1:5000`
   - After the first time, the Simple Browser tab will already be there — just hit refresh.

---

## If You Ever Move or Rename This Folder

The virtual environment will break. Fix it by rebuilding:

```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Then start the server normally with `python3 run.py`.

---

## Living Judge Corpus (CourtListener)

BriefTune can pull new opinions (and, where available, oral argument transcripts) for tracked judges directly from CourtListener.

1. Get a free API token: sign in at https://www.courtlistener.com/sign-in/, then find your token under your profile's API settings.
2. Open the `.env` file in the project root and paste your token in:
   ```
   COURTLISTENER_API_TOKEN=your-token-here
   ```
   This file is gitignored, so the token never gets committed. It's loaded automatically every time you run `python3 run.py` — no `export` command needed.
3. Track a judge from the homepage ("Track a judge on CourtListener" panel), then click "Sync now" — or "Sync all tracked judges now" to refresh everyone at once.
4. New opinions land under `data/courtlistener_sync/Judge <Name>/` and get ingested through the same folder pipeline as a manual "Load folder" run — deduplicated by content hash, judge auto-assigned.

### Automating it on a schedule

Run this from the project root (with the venv active, `.env` filled in) to sync every tracked judge without opening the app — it reads `.env` the same way `run.py` does:

```bash
.venv/bin/flask --app run.py courtlistener-sync-all
```

Example crontab entry to run it every morning at 6am:

```
0 6 * * * cd /path/to/brieftune && .venv/bin/flask --app run.py courtlistener-sync-all >> data/courtlistener_sync.log 2>&1
```

Note: oral argument transcript text depends on CourtListener's speech-to-text field, which is newer and hasn't been verified against a live response — opinions are reliable today, transcripts may need a small field-name adjustment once you test against your real token.

---

## Auto-Research (billed per verification) — built 2026-07-02

**What it is:** on each flagged brief-mention card (below the manual "Verify this case" form), there's now a second collapsible option, "Auto-Research (billed per verification)." Instead of you or Claude-in-chat manually reading the case, BriefTune's own server calls the Anthropic API directly to (1) read the judge's already-synced opinion and decide which party's brief is discussed and whether that party's argument prevailed, and (2) only if that party won, search the web for the real brief and attach its text — automatically recording the case as `verified_winning` (with brief text) or `verified_not_winning`. This is a genuine, metered API cost, separate from your Cowork/chat access.

**To turn it on:** get a key at https://console.anthropic.com/settings/keys and paste it into `.env`:
```
ANTHROPIC_API_KEY=your-key-here
```
Until this is set, the card shows a note instead of the controls, and the manual verify path still works exactly as before — nothing breaks if you leave this blank.

**The two safety sliders**, shown once a key is configured:
- **Loop limiter** — caps how many API round-trips one run can take (default 10, range 3–20) before giving up and marking the case "inconclusive" rather than continuing indefinitely. This is a technical backstop; in practice the price limiter usually stops a run first.
- **Price limiter** — the hard dollar ceiling on estimated spend for one verification (default $0.50, range $0.25–$2.00). If the running cost estimate would cross it, the run stops early and reports whatever it found rather than ever going over.

**Where the code lives:** `app/ai_verification.py` (the job/loop itself), two new routes in `app/routes.py` (`/courtlistener/auto-verify/<candidate_id>` to start a run, `/auto-verify-status/<job_id>` to poll it), a new `app/templates/auto_verify_status.html` status page, and the new UI block inside the brief-candidate card loop in `app/templates/index.html`. Tests: `tests/test_ai_verification.py` (10 tests, all passing, using a mocked Anthropic client — no real API calls happen in the test suite).

**Real costs are estimates, not verified against Anthropic's live pricing page** — `INPUT_COST_PER_MTOK`, `OUTPUT_COST_PER_MTOK`, and `WEB_SEARCH_COST_PER_USE` near the top of `ai_verification.py` should be double-checked before relying on the price limiter for real client billing. The model used is `claude-sonnet-5`, set as `DEFAULT_MODEL` in that same file (overridable via an `AI_VERIFICATION_MODEL` config key if you ever want to swap in a cheaper model).

**Not yet done / open follow-ups:**
- No aggregate/cumulative cost display exists yet (each run shows its own cost on its own status page, but there's no "total spent this month" view anywhere in the UI).
- Real API cost math has not been validated against an actual Anthropic bill — worth running one real (non-mocked) verification once a real API key is added, to sanity-check the estimate against the real invoiced amount.

---

## CourtListener sync reliability fix — built 2026-07-03

The 429 rate-limit bug flagged above is now fixed in `courtlistener_sync.py`. Three changes, all covered by new tests in `tests/test_courtlistener_sync.py`:

- **Glance before pull:** before fetching an opinion's full text, the sync checks whether a file for that `cluster_id` already exists on disk in the judge's folder. If so, it's skipped — no network calls spent re-fetching something already saved. This is what makes a re-run after a partial failure cheap and fast instead of starting over.
- **Retry with backoff:** every CourtListener GET now goes through `_get_with_retry`, which catches HTTP 429s, honors `Retry-After` if CourtListener sends one, and otherwise backs off exponentially (up to `MAX_FETCH_RETRIES`, currently 4 tries) before giving up on that one item.
- **Watermark safety:** `last_synced` (the timestamp used to ask CourtListener for "what's new since last time") only advances when a sync run finishes with zero errors. If anything failed to fetch, the watermark stays put, so the next "Sync now" re-asks for the same window rather than silently losing whatever didn't make it in — combined with the skip-if-already-saved check, that retry is cheap since everything that did succeed gets skipped instantly.

A new `skipped_existing` count is now shown in the CLI output and in the flash messages on the homepage after a sync, so it's visible when a run is mostly just confirming what's already there versus pulling something new.

---

## Starting a New Python/Flask Project

```bash
# 1. Create the folder
mkdir ~/Desktop/Claude/Python\ Projects/projectname
cd ~/Desktop/Claude/Python\ Projects/projectname

# 2. Create and activate the venv
python3 -m venv .venv
source .venv/bin/activate

# 3. Install packages — always use python3 -m pip, never bare pip
python3 -m pip install flask
python3 -m pip install -r requirements.txt
```

---

## Two Rules That Prevent Most Problems

1. **Always use `python3 -m pip`** instead of bare `pip` — guarantees packages install to the right Python
2. **Never move a project folder after creating the venv** — if you must move it, rebuild the venv using the steps above

---

*BriefTune © 2026 George Ellis. All rights reserved.*
