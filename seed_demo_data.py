"""One-off demo seeder.

Run this once (`python3 seed_demo_data.py`) to create a fake tracked judge,
"Judge Demo," with a real style profile and one unverified flagged brief
mention -- so you can see the entire Precedent brief signal workflow live in
your own browser without waiting on a real CourtListener sync to happen to
turn up an opinion that mentions a brief.

This writes into the SAME data files your running app already reads
(data/tracked_judges.json, data/judge_style_profiles/, and
data/brief_mention_candidates.json), so if `flask run` is already going, you
just need to refresh the page afterward -- no restart required.

Safe to re-run: adding the same judge twice is a no-op, and flagging the same
case twice is also a no-op (both are keyed by a stable id).
"""

from app import create_app
from app.brief_candidates import flag_brief_mentions
from app.courtlistener_sync import add_tracked_judge
from app.style_profile import build_style_profile, save_style_profile

JUDGE_NAME = "Judge Demo"
JUDGE_COURT = "demo"

# This becomes the judge's "style fingerprint" -- word frequency + sentence
# cadence -- that the Judge style signal compares your draft against.
STYLE_SOURCE_TEXT = (
    "We conclude that equitable relief must remain narrowly tailored to the "
    "parties before the court. The record demonstrates that the arguments "
    "presented were both timely and well supported. Accordingly, the court "
    "adopts this reasoning in full."
)

# This is what a real CourtListener sync would have pulled in as a new
# opinion. It quotes a "brief" next to a brief-reference term and verb, which
# is exactly the pattern flag_brief_mentions() scans for.
FLAGGED_OPINION_TEXT = (
    'The appellant\'s brief argued, "Equitable relief must remain narrowly '
    'tailored to the parties before the court." The panel agreed with that '
    "reasoning and adopted it below."
)

DEMO_CASE_NAME = "Doe v. Roe (Demo)"
DEMO_CLUSTER_ID = 999001


def main() -> None:
    app = create_app()

    with app.app_context():
        judge = add_tracked_judge(app.config, JUDGE_NAME, JUDGE_COURT)
        print(f"Tracked judge ready: {judge.name} (id={judge.id})")

        profile = build_style_profile(JUDGE_NAME, [STYLE_SOURCE_TEXT])
        save_style_profile(app.config, profile)
        print(f"Style profile saved for {JUDGE_NAME}.")

        flagged = flag_brief_mentions(
            app.config,
            judge.id,
            JUDGE_NAME,
            DEMO_CLUSTER_ID,
            DEMO_CASE_NAME,
            "2025-01-01",
            FLAGGED_OPINION_TEXT,
        )
        if flagged:
            print(f'New flagged candidate created: "{DEMO_CASE_NAME}" (unverified).')
        else:
            print(f'"{DEMO_CASE_NAME}" was already flagged -- nothing new to create.')

    print()
    print("Next steps in your browser (refresh if the app is already running):")
    print('  1. Under "Track a judge on CourtListener," you should now see "Judge Demo."')
    print('  2. Under "Flagged brief mentions," you should see "Doe v. Roe (Demo)," unverified.')
    print('  3. Click "Verify this case," choose "Brief prevailed -- use as precedent," and paste in:')
    print()
    print('     Equitable relief must remain narrowly tailored to the parties before the court.')
    print()
    print('  4. Save the verification -- this feeds the Precedent brief signal for Judge Demo.')
    print('  5. Under "Upload your draft brief," upload a .txt file containing:')
    print()
    print(
        "     We conclude that equitable relief here must remain narrowly tailored to the "
        "parties before this court, consistent with the reasoning set out below."
    )
    print()
    print('  6. In "Affinity score weights," select "Judge Demo" from the dropdown, then "Run analysis."')
    print('  7. Check "Why this score" -- you should see real factors from BOTH the Judge style')
    print("     signal (vocabulary/cadence match) and the Precedent brief signal (shared wording")
    print("     with the brief you just verified).")


if __name__ == "__main__":
    main()
