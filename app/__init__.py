from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from .data_loader import load_opinions, load_transcripts


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    base_dir = Path(__file__).resolve().parent.parent

    # Load variables from a project-root .env file (e.g. COURTLISTENER_API_TOKEN)
    # without overriding any that are already set in the real environment.
    load_dotenv(base_dir / ".env", override=False)
    app.config.from_mapping(
        SECRET_KEY="dev",
        OPINION_DATA_DIR=base_dir / "data" / "opinions",
        TRANSCRIPT_DATA_DIR=base_dir / "data" / "transcripts",
        FIRM_CONFIDENTIAL_DIR=base_dir / "data" / "firm_confidential",
        FIRM_CONFIDENTIAL_KEY_PATH=base_dir / "data" / "firm_confidential.key",
        AUDIT_LOG_PATH=base_dir / "data" / "audit.log",
        PROCESSED_FILES_PATH=base_dir / "data" / "processed_files.json",
        COURTLISTENER_API_TOKEN=os.environ.get("COURTLISTENER_API_TOKEN", ""),
        COURTLISTENER_SYNC_DIR=base_dir / "data" / "courtlistener_sync",
        TRACKED_JUDGES_PATH=base_dir / "data" / "tracked_judges.json",
        JUDGE_STYLE_PROFILE_DIR=base_dir / "data" / "judge_style_profiles",
        BRIEF_MENTION_CANDIDATES_PATH=base_dir / "data" / "brief_mention_candidates.json",
        ANTHROPIC_API_KEY=os.environ.get("ANTHROPIC_API_KEY", ""),
    )

    if test_config:
        app.config.update(test_config)

    from .privacy import ensure_privacy_storage

    ensure_privacy_storage(app.config)

    app.config["OPINION_SAMPLES"] = load_opinions(app.config["OPINION_DATA_DIR"])
    app.config["TRANSCRIPT_SAMPLES"] = load_transcripts(app.config["TRANSCRIPT_DATA_DIR"])

    from .routes import bp

    app.register_blueprint(bp)

    register_cli_commands(app)

    return app


def register_cli_commands(app: Flask) -> None:
    @app.cli.command("courtlistener-sync-all")
    def courtlistener_sync_all() -> None:
        """Sync every tracked judge against CourtListener (safe to run on a cron/launchd schedule)."""
        from .courtlistener_sync import sync_all_judges

        results = sync_all_judges(app.config)
        if not results:
            print("No tracked judges yet. Add one from the BriefTune homepage first.")
            return

        for result in results:
            print(
                f"{result.judge_name}: {result.opinions_found} opinion(s), "
                f"{result.oral_arguments_found} oral argument(s) found, "
                f"{result.files_written} file(s) written, "
                f"{result.skipped_existing} already on disk (skipped)."
            )
            for error in result.errors:
                print(f"  ! {error}")
