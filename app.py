"""Main Flask application entry point for the Organ Allocation System."""

from __future__ import annotations

import os
import logging
from flask import Flask, render_template, Response, redirect, url_for, session
from dotenv import load_dotenv

from routes import api_bp

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Application factory for configuring and initializing the Flask instance."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    secret_key = os.getenv("SECRET_KEY")
    if app_env == "production" and not secret_key:
        raise RuntimeError("SECRET_KEY must be configured when APP_ENV=production.")
    app.secret_key = secret_key or "dev-only-change-this-secret-key"
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=(app_env == "production"),
    )

    # Register API blueprint
    app.register_blueprint(api_bp)

    @app.route("/", methods=["GET"])
    def index() -> str:
        """Serve the administrative interface only to signed-in users."""
        if not session.get("user_id"):
            return redirect(url_for("login_page"))
        return render_template("index.html")

    @app.route("/login", methods=["GET"])
    def login_page() -> str:
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template("login.html")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug_mode = os.getenv("FLASK_DEBUG", "True").strip().lower() in ("true", "1", "yes")
    logger.info("Starting Organ Allocation Prototype on port %d (debug=%s)", port, debug_mode)
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
