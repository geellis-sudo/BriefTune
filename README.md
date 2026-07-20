# BriefTune

This is a small Flask app that helps you study judge opinions so you can improve the language of briefs that will be filed before different judges.

It is built to run even before you add real judge opinion files. If no files exist yet under `data/opinions/`, the app falls back to bundled sample opinions so you can try the full flow immediately.

## What it does

- Shows an opinion library so you can study judge response patterns
- Analyzes text for a few beginner-friendly writing signals such as long sentences, passive voice hints, repeated phrasing, hedging, and dense legal jargon
- Displays suggestions in a simple results page intended to help brief drafting land more effectively with judges
- Can track judges on CourtListener and pull their new opinions (living corpus) straight into the judge's file library — see `WORKFLOW.md` for setup

## Run it locally

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Start the app:

   ```bash
   .venv/bin/python run.py
   ```

4. Open the URL printed in the terminal, usually `http://127.0.0.1:5000`.

## Add real opinion files later

Place `.txt` files in `data/opinions/`. Each file can contain one opinion or excerpt. You can also upload `.txt` or PDF files in the app; PDFs will be converted to text automatically before analysis. The app will automatically load `.txt` files on startup, letting you build a judge-specific corpus over time.

## Tests

Run the test suite with:

```bash
pytest
```

## Security & confidentiality

Draft briefs are privileged material — read `SECURITY.md` before using BriefTune on a real matter. The short version: the core analysis runs entirely locally; uploads are encrypted at rest and redacted (your listed terms plus SSNs/phones/emails) before anything is indexed; the optional AI features (Writing Coach, Auto-Research) send anonymized or public-record text to the Anthropic API and only run if you set `ANTHROPIC_API_KEY` in `.env`. Before enabling those features on privileged documents, confirm with your firm's IT/compliance function that the API account is covered by an appropriate data agreement (ideally zero-data-retention). Stored uploads can be reviewed and deleted from the app's Stored documents page. This is engineering guidance, not legal advice — the firm's own ethics/compliance review still governs.
