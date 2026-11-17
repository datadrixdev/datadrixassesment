import os
from dotenv import load_dotenv

# Load local .env file if present
load_dotenv(".env", override=True)

from app import create_app
from app.extensions import db
from app.services.question_service import seed_questions_from_file

app = create_app(os.environ.get("FLASK_ENV", "development"))

if __name__ == "__main__":
    with app.app_context():
        # Auto-create tables and seed questions if empty
        db.create_all()

        # Ensure column migrations for SQLite
        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE assessment_attempt ADD COLUMN vision_warning_count INTEGER DEFAULT 0 NOT NULL"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        try:
            count = seed_questions_from_file()
            if count > 0:
                print(f"[ApexAssess] Successfully seeded {count} questions into the question bank.")
        except Exception as e:
            print(f"[ApexAssess] Question bank check: {e}")

    port = int(os.environ.get("PORT", 5000))
    print(f"[ApexAssess] Starting development server on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
