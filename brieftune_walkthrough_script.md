# BriefTune In-App Walkthrough — Narration Script

Format: `[start–end]` timestamp, `TARGET:` the DOM element/section to highlight (selector noted for the tour build), then narration.
Timestamps are estimates for pacing — actual cut points should follow the recorded VO, not the reverse.

---

## 1. Overview / purpose — 0:00–0:20 (20s)
**TARGET:** `.hero` (header/tagline — no highlight needed, avatar full-frame or small corner bubble over the page as a whole)

> "BriefTune helps you tune the language of a brief to the judge — or panel — it's actually going to. Every judge has a style: some want short sentences and plain language, others expect denser, more formal prose. BriefTune reads that style straight from a judge's own opinions, compares it to your draft, and shows you exactly where the two don't match. Let's walk through how."

---

## 2. Upload your brief — 0:20–0:45 (25s)
**TARGET:** `.sample-picker--draft`, specifically `#draft_file` / `.draft-upload-button` and the "Run analysis" button

> "Start by uploading your draft — a .txt or PDF works. This is the brief you're about to file. Once it's in, BriefTune will use whatever comparison settings are currently set — you can leave the defaults or dial them in first, which is what we'll do next."

---

## 3. Track the judge(s) it'll be submitted to — 0:45–1:10 (25s)
**TARGET:** `.sample-picker--courtlistener`, `#courtlistener_judge_name`, `#courtlistener_court`, "Track judge" button, `.tracked-judges-table`

> "Before comparing anything, tell BriefTune which judge — or panel — you're writing for. Enter their name and, if you know it, the court code, then track them. Tracking pulls that judge's opinions in from CourtListener — the first sync grabs everything on record, and every sync after that only pulls what's new, so it stays current without re-fetching what you already have."

---

## 4. How the precedent pool gets built — 1:10–1:55 (45s)
**TARGET:** `.sample-picker--brief-candidates`, `.brief-candidate-card`, the "Verify this case" details block, the "Auto-Research" details block, and the bulk "Run Auto-Research on all unverified cases" button

> "Here's where it gets useful: as BriefTune syncs a judge's opinions, it also scans them for language that sounds like the judge is discussing a specific brief — not just citing a case, but actually referencing arguments someone made. Those show up here as flagged mentions. You decide the outcome: did that brief win, lose, or was this just a false positive? If it won, paste the brief text in and it becomes precedent — a real example of language that landed with this judge. If you'd rather not read the case yourself, Auto-Research can do it — it has Claude read the opinion, determine who prevailed, and pull the brief text automatically, with a step limit and a price cap so it never runs away from you. Got a handful flagged at once? Run Auto-Research on all of them in one click — each case is researched independently and in parallel, so you're not waiting on them one at a time."

---

## 5. Select comparison sources — 1:55–2:20 (25s)
**TARGET:** `.sample-picker--weights` → `#compare_judge_id`; `.sample-picker--folder` → `#firm_folder_path`

> "Now choose what to compare your draft against. Pick a tracked judge, and BriefTune uses both their opinion style and any briefs verified as winning in front of them. Or point it at a folder of your firm's own winning briefs instead — or use both together. Run both, and you'll get two separate scores with a toggle to flip between them."

---

## 6. Affinity Score explained — 2:20–2:40 (20s)
**TARGET:** `.affinity-score-heading` and its `<details class="info-note">`

> "All of that feeds into one number: the Affinity Score. It's not a grammar score — it's a measure of how closely your draft's language matches what's actually worked, or been written, in front of this specific judge."

---

## 7. The two weighting sliders — 2:40–3:00 (20s)
**TARGET:** `.weight-sliders`, `#weight_judge_style`, `#weight_precedent_brief`

> "These two sliders control how that score is calculated — judge style versus winning-brief precedent — and they're linked, always adding to 100%. Weight it however matters more to you. Haven't verified any winning briefs for this judge yet? That signal's share just shifts automatically to the other one."

---

## 8. Privilege / anonymization — 3:00–3:25 (25s)
**TARGET:** `#redact_terms` (the "Names or info to redact" field), plus the "How it works" `.helper-panel` at page bottom

> "One more thing before you upload anything sensitive: list any names or identifying details here — your client's name, their company, an address — and BriefTune redacts every exact match before analysis ever runs. Social Security numbers, phone numbers, and email addresses are always redacted automatically, whether you list them or not. Case numbers and dollar figures stay visible — they're useful context and aren't privileged on their own. And this all happens locally: nothing about the brief itself leaves this machine unless you separately trigger a judge sync or Auto-Research."

---

## 9. Walk through actual results — 3:25–4:00 (35s)
**TARGET:** `.summary-grid` → `.highlight-block` ("Why this score") → `.quality-block` (Writing Quality + flagged examples) → brief language passages section → `.comparison-toggle` (if present)

> "Run the analysis, and here's what comes back: word and sentence counts, how many issues got flagged, and your Affinity Score — with a plain-language breakdown of why. Below that, a Writing Quality score with specific flagged sentences and suggested rewrites for each. If any of your language actually mirrors a verified winning brief, that's called out too — those passages get weighted more heavily since they're proven to work. And if you ran two comparisons at once, this toggle switches between them."

---

## 10. AI Writing Coach (optional add-on) — 4:00–4:25 (25s)
**TARGET:** `#run_ai_coach` checkbox on the upload form, then the "AI Writing Coach" `.quality-block` section on the results page

> "One more option, back on the upload form: check 'Also run the AI Writing Coach' before you analyze, and you'll get a deeper editorial pass alongside the automated checks — argument structure, persuasiveness, tone, the kind of close read a pattern-matcher can't do. It's optional and billed per run, so it's there when you want the extra eye, not running by default."

---

## Close (optional, not counted in feature beats)
> "That's BriefTune — upload, track, compare, and tune. Close this and give it a try."

---

**Total runtime:** ~4:25 (265s) across 10 feature beats + intro/close.
**Next steps for build:** each `TARGET` selector above becomes a keyframe in the JS tour timeline (task #4), keyed to these approximate timestamps once the actual VO/avatar render locks the real timing.
