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
    )

    if test_config:
        app.config.update(test_config)

    app.config["OPINION_SAMPLES"] = load_opinions(app.config["OPINION_DATA_DIR"])
    app.config["TRANSCRIPT_SAMPLES"] = load_transcripts(app.config["TRANSCRIPT_DATA_DIR"])

    from .routes import bp

    app.register_blueprint(bp)

    return app
