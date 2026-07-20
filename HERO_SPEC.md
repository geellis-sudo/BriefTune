# BriefTune Landing Hero — Implementation Spec

**For:** Claude Code, working in the BriefTune repo
**Source mockup:** `mockups/brieftune_hero_A_tuning_waveform.html` (copied into this repo — lift code from it directly rather than reinventing)
**Goal:** Replace the current utilitarian landing/hero area with the "tuning waveform" design from the mockup, integrated into the real app without disturbing any existing functionality.

## The concept

Two animated waveforms on a canvas behind the hero content: a **gold wave** (the judge's writing style) and a **blue wave** (the user's draft) that slowly drifts into alignment with it on a repeating cycle. An "Affinity Score" chip with a small animated equalizer ticks its number up as the waves converge. This animation *is* the product pitch — a draft being tuned to a judge.

## Files to touch

- `app/templates/index.html` — hero markup + inline canvas script (or a new `static/hero.js`)
- `app/templates/base.html` — only if shared structure/head changes are needed
- `app/static/styles.css` — hero styles; adopt the mockup's palette variables

Do **not** modify: `routes.py`, `analyzer.py`, `privacy.py`, or any analysis/backend code. This is a purely presentational change.

## Integration requirements

1. **The existing UI must keep working.** The current page has functional sections the hero sits above: draft upload (`.sample-picker--draft`, `#draft_file`), judge tracking (`.sample-picker--courtlistener`), brief candidates (`.sample-picker--brief-candidates`), comparison weights/sliders (`.sample-picker--weights`, `.weight-sliders`), firm folder picker (`.sample-picker--folder`), and the results area (`.summary-grid`, etc.). None of their selectors, IDs, or behavior may change — a video tour overlay (separate upcoming task) keys off these exact selectors.
2. **Canvas stays behind content.** The waveform canvas is `position:absolute; inset:0` inside the hero section only — not a full-page background. Form controls must remain fully clickable; nothing in the hero may intercept pointer events outside its own buttons.
3. **Palette and type** (from the mockup): navy `#0a1120`/`#101c33`, gold `#c9a227`/`#e3c565`, blue `#6fa3d8`, ivory `#f4efe4`, muted `#8fa0b8`. Georgia/serif for display headings, existing sans for body/UI. Extend this palette to the rest of the page enough that the hero doesn't look bolted on — but keep the form sections readable and familiar (dark theme migration of the form area is in scope if it's low-risk; if the existing styles fight it, keep the forms light and use a clean transition between hero and form area).
4. **Hero content:** logotype ("Brief" ivory + "Tune" gold), kicker "Judicial writing-style analysis", headline "Tune your brief to the judge who'll *actually* read it.", subhead from the mockup, primary CTA "Upload a draft" (smooth-scrolls to `#draft_file`'s section), ghost CTA "Watch the 2-minute overview" — **this button must exist but can be a no-op stub with `id="tour-trigger"`**; the tour overlay task will wire it up.
5. **Legend** (bottom-right of hero): "Your draft" (blue) / "The judge's style" (gold) — this labels the animation and carries the metaphor.
6. **Performance & accessibility:**
   - `prefers-reduced-motion: reduce` → render one static, nearly-aligned frame; no `requestAnimationFrame` loop, no CSS equalizer animation.
   - Cap devicePixelRatio at 2; step the waveform sampling (every ~3px) as in the mockup.
   - Pure canvas 2D, no external libraries, no build tooling. Everything works offline from the Flask static folder.
   - Degrade gracefully if canvas is unavailable (static gradient background).
7. **No layout shift for returning users' muscle memory:** the form sections keep their current order and structure below the hero.

## The animation (reference implementation is in the mockup)

- Judge wave: fixed harmonics, gold, subtle glow, plus two faint echo traces.
- Draft wave: separate harmonic set, blue; each frame interpolates toward the judge wave by a convergence factor oscillating ~0.35→1.0 on a slow (~25s) cycle.
- Affinity chip number = `round(58 + convergence * 40)`.
- Faint horizontal grid lines behind the waves.

## Process

1. Read the mockup file in full before writing anything.
2. Run the Flask app locally and verify the current page renders before changes (`python -m flask run` or however the repo's README says).
3. Implement, then verify: hero renders, animation runs, all form sections function (upload field accepts a file, judge tracking form submits, sliders move), reduced-motion works (toggle in devtools rendering emulation), and no console errors.
4. Commit as a single focused commit, e.g. `Add tuning-waveform landing hero`. **Note:** as of 2026-07-17, local `main` is 1 ahead of `origin/main` (commit `ca1345b`, "Match brief language against winning corpora"). Local is authoritative — verify with `git status -sb` before any pull/rebase, and remind the user the push is pending.

## Out of scope (do not build now)

- The video tour overlay and its timeline (separate task; just leave the `#tour-trigger` stub).
- Any change to analysis logic, anonymization, CourtListener sync, or Auto-Research.
- 3D/Three.js elements — a second mockup direction was considered and rejected for now.
