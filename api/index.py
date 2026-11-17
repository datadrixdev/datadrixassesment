import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.services.question_service import seed_questions_from_file

app = create_app(os.environ.get("FLASK_ENV", "production"))

with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text
        db.session.execute(text("ALTER TABLE assessment_attempt ADD COLUMN vision_warning_count INTEGER DEFAULT 0 NOT NULL"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    try:
        seed_questions_from_file()
    except Exception:
        pass
