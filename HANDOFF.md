# BriefTune — Hand-Off Summary
*As of July 1, 2026*

---

## Project Identity
- **Name:** BriefTune © 2026 George Ellis. All rights reserved.
- **Purpose:** Flask-based legal writing tool that helps attorneys align brief language with judge-specific preferences
- **GitHub:** Private repo named `BriefTune`
- **Local path:** `/Users/georgeellis/Desktop/Claude/Python Projects/brieftune/`

---

## What's Built

### Scoring
- **Affinity Score** (0–100): Judge-specific tonal alignment
- **Writing Quality Score** (0–100): Based on Garner legal writing principles, with flagged examples
- **Affinity Score Weighting Sliders**: User-adjustable weights for three signal types — Vocabulary signal, Issue framing signal, Brief reference signal

### Input Methods
- Pasted text
- `.txt` and PDF file uploads
- Firm-supplied documents (anonymized before processing)
- Folder-based batch loading with automatic judge detection from folder names (Load Folder button present in UI)

### Infrastructure
- Local ChromaDB vector database storing judge preference patterns
- Audit log tracking all document activity
- Confidentiality notice displayed prominently in UI

### Source Types Supported
1. Judicial opinions
2. Appellate oral argument transcripts
3. Firm-supplied winning briefs

---

## Current Technical State
- **Server runs on:** `http://127.0.0.1:5000`
- **Python command:** `python3` (not `python`)
- **Port note:** Previously ran on 5001 to avoid Apple ControlCe/AirTunes conflict; now back on 5000
- **Dependencies:** All installed via `python3 -m pip install -r requirements.txt`
- **Startup:** See `WORKFLOW.md` in this folder

### Project Structure
```
brieftune/
├── app/
├── data/
├── tests/
├── .venv/
├── .gitignore
├── README.md
├── requirements.txt
├── run.py
├── WORKFLOW.md
└── HANDOFF.md
```

---

## Outstanding Items

### Quick fixes (not yet done)
1. **Typo:** `judcial` → `judicial` in the homepage subtitle
2. **"How it works" section:** Needs updating to mention all three source types (currently missing firm-supplied winning briefs)

### To verify
- Folder-based batch loading: Load Folder button is present in the UI — confirm end-to-end functionality works after the folder move
- Confirm port is consistently set to 5000 in `run.py` so it doesn't switch between sessions

### Planned (not yet built)
- Nothing confirmed outstanding beyond the two quick fixes above — sliders and folder loading appear complete

---

## Session Notes (from July 1, 2026 session)
- Project was reorganized from `Judge Language-Decision Tool` (old name, bad convention) to `brieftune` (Python standard naming)
- Moved to: `~/Desktop/Claude/Python Projects/brieftune/`
- After the move, the venv broke — rebuilt by running `python3 -m pip install -r requirements.txt`
- `brieftune.textClipping` is an untracked stray file in the root — safe to delete
- `WORKFLOW.md` created with full startup and new-project instructions
