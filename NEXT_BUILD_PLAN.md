# Next build: Firm-folder comparison + slider cleanup — locked plan

STATUS: BUILT on 2026-07-03. All 57 tests pass. One item below (#5, the "Judge style
signal" naming) is still open per its own note -- confirm with George before renaming.

Status as of 2026-07-03: fully discussed and confirmed with George in chat. Not yet built.
This file is the durable, literal spec — if the chat context ever gets long enough that
Claude needs to re-derive intent, read this file instead of guessing.

To kick this off: George just needs to say something like "go ahead and build the
firm-folder comparison plan" (or any clear affirmative referencing this file/plan) in the
BriefTune conversation. Claude should then read this file and execute it directly, without
re-litigating any of the decisions below -- they are all settled.

## Already done (do not redo)

The three generic, non-judge-specific sliders have already been deleted from the running
code, confirmed working:
- "Vocabulary signal" (fixed word list) -- deleted.
- "Issue framing signal" (fixed phrase list) -- deleted. Note: the underlying
  `FRAMING_PATTERNS` constant in `analyzer.py` was KEPT, because `style_profile.py` still
  depends on it for the legitimate judge-specific `framing_hit_rate` calculation. Only the
  generic slider-driven bonus was removed.
- "Brief reference signal" -- deleted. Note: `extract_brief_language_references()` and the
  `brief_language_references` data were KEPT (still used by results.html's "Brief language
  passages" section and issue weighting) -- only the slider-driven bonus/penalty in
  `build_summary()` was removed.

Remaining sliders in the UI today: "Judge style signal" and "Precedent brief signal."

## What's being built now

### 1. Replace the "Load a local folder" section entirely

Delete:
- The `folder_context` dropdown (Auto-detect / specific_judge / firm / mixed).
- The `folder_judge_name` text input + its datalist.
- The `/load-folder` route (`load_folder()` in `app/routes.py`) and its one-off
  "here's what I found in this folder" confirmation behavior.
- The corresponding section markup in `app/templates/index.html`.

KEEP UNTOUCHED: `app/folder_ingest.py`'s job-processing machinery (`FolderJob`, `JOB_STORE`,
`start_folder_processing`, `folder_status.html`) -- CourtListener sync
(`courtlistener_sync.py`'s `sync_judge()`) still depends on this to file newly-synced
opinions into the sample picker. Do not delete or break that path.

Replace with: a single field, something like "Firm winning briefs folder," where the user
types/pastes a folder path (option 1 from the browse-vs-type discussion -- no native folder
picker, since browsers can't expose real filesystem paths to JS anyway). One explanatory
sentence underneath, in the same style/length as the existing slider hints. This field lives
INSIDE the main analysis form (not a separate button/action), and is read live every time
"Run analysis" is submitted -- no persistence, no saved/tracked list of folders, no
background job, no content-hash dedup. Just a fresh full read of whatever's currently in
that folder, every run. (Rationale: unlike CourtListener, local disk reads are free and
instant, so there's no cost to always re-reading fresh -- persistence would only add
complexity for no benefit here.)

### 2. Wire the folder's contents into scoring

When the folder path field is filled in on an `/analyze` submission:
- Read every supported file in that folder synchronously (reuse
  `read_folder_document_text()` and `SUPPORTED_FOLDER_SUFFIXES` from `folder_ingest.py`,
  called directly/inline -- do NOT use the async `FolderJob`/thread system for this; that's
  overkill for a synchronous read needed within the same request).
- Build a style profile from those texts using the EXISTING `build_style_profile()` function
  in `style_profile.py` (already generic -- takes a name + list of texts, doesn't know or
  care that it's "a judge"). Pass something like `"your firm's winning briefs"` as the label.
- Treat the folder's full list of texts directly as the "verified winning briefs" pool for
  `precedent_alignment_score()` in `brief_candidates.py` (also already generic). No
  flag/verify workflow needed for folder-sourced text -- the whole folder is trusted as wins
  by construction, since the user put it there deliberately.

### 3. Support BOTH a tracked judge AND the firm folder being active at once

Confirmed with George: these are NOT mutually exclusive, and should NOT be blended/combined
into one number. If both are active:
- Compute TWO independent `AnalysisSummary` results -- one using the judge's style profile +
  judge's verified winning briefs (existing behavior, unchanged), one using the folder's
  freshly-built style profile + the folder's full text list as the winning-briefs pool.
- Both use the SAME slider weight values (Judge style signal / Precedent brief signal
  sliders) applied independently to each computation -- no separate weight controls per
  source.
- This likely means `analyze_text()` / `build_summary()` in `analyzer.py` need to support
  returning a dict/list of named summaries (e.g. keyed `"judge"` / `"folder"`) instead of a
  single `summary`, when more than one comparison source is active. If only one source (or
  neither) is active, this should still work exactly as it does today -- a single summary,
  no behavior change, no new required fields breaking existing callers/tests.

### 4. Results page: default + toggle, not blended display

On `results.html`, when two summaries exist: show one by default (doesn't matter which),
plus a simple button/toggle to switch to the other. Both summaries are already rendered in
the response (no second page load) -- toggle is just client-side show/hide via a little
inline JS, matching the pattern already used for the slider-label-update scripts.

### 5. Naming loose end -- CONFIRM WITH GEORGE BEFORE FINALIZING, DO NOT SILENTLY RENAME

"Judge style signal" reads oddly once it can apply to a folder instead of / alongside a
judge. Claude proposed renaming it to something source-agnostic (e.g. "Style signal") but
this was NOT explicitly confirmed by George -- flag it and get a real answer on the label
before locking it in, same as every other slider-language decision this whole thread.

## Test/verification expectations

- Update or remove `tests/test_routes.py` cases tied to the old `/load-folder` route.
- Add tests for: folder-only scoring (no judge selected), judge-only (unchanged/regression),
  both-active producing two independent summaries, and neither-active (baseline, no
  comparison signals -- should still work, matching current post-slider-cleanup behavior).
- Run the full `pytest` suite at the end and confirm everything passes before calling this
  done -- do not skip this step even though slider-cleanup edits earlier in this thread had
  their own verification deferred at George's request; this is a new, separate chunk of work.
