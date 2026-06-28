from __future__ import annotations

from pathlib import Path

from flask import Flask

from .data_loader import load_opinions, load_transcripts


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    base_dir = Path(__file__).resolve().parent.parent
    app.config.from_mapping(
        SECRET_KEY="dev",
        OPINION_DATA_DIR=base_dir / "data" / "opinions",
        TRANSCRIPT_DATA_DIR=base_dir / "data" / "transcripts",
        FIRM_CONFIDENTIAL_DIR=base_dir / "data" / "firm_confidential",
        FIRM_CONFIDENTIAL_KEY_PATH=base_dir / "data" / "firm_confidential.key",
        AUDIT_LOG_PATH=base_dir / "data" / "audit.log",
        PROCESSED_FILES_PATH=base_dir / "data" / "processed_files.json",
    )

    if test_config:
        app.config.update(test_config)

    from .privacy import ensure_privacy_storage

    ensure_privacy_storage(app.config)

    app.config["OPINION_SAMPLES"] = load_opinions(app.config["OPINION_DATA_DIR"])
    app.config["TRANSCRIPT_SAMPLES"] = load_transcripts(app.config["TRANSCRIPT_DATA_DIR"])

    from .routes import bp

    app.register_blueprint(bp)

    return app
