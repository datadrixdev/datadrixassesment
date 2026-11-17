import os
from datetime import datetime, timezone
from flask import Flask, render_template
from app.config import config_by_name
from app.extensions import db, csrf
from app.routes.main import main_bp
from app.routes.assessment import assessment_bp
from app.routes.results import results_bp

def create_app(config_name=None):
    """Application factory for the online assessment platform."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name["default"]))

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(assessment_bp)
    app.register_blueprint(results_bp)

    # Register error handlers
    @app.errorhandler(400)
    def bad_request(error):
        return render_template("errors/400.html", error=error), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html", error=error), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html", error=error), 404

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/500.html", error=error), 500

    # Global template context
    @app.context_processor
    def inject_context():
        return {
            "current_year": datetime.now(timezone.utc).year,
            "app_name": "Datadrix",
            "app_tagline": "Learn Programming, Data Science & Tech Assessment"
        }

    # Register CLI commands
    @app.cli.command("init-db")
    def init_db():
        """Initialize database tables."""
        with app.app_context():
            db.create_all()
            print("Database initialized successfully.")

    @app.cli.command("seed-db")
    def seed_db():
        """Seed the question bank from seed/questions.json."""
        from app.services.question_service import seed_questions_from_file
        with app.app_context():
            db.create_all()
            count = seed_questions_from_file()
            print(f"Question bank seeded: {count} questions added.")

    return app
