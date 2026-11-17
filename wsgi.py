import os
from app import create_app
from app.extensions import db
from app.services.question_service import seed_questions_from_file

# Production WSGI application instance
application = create_app(os.environ.get("FLASK_ENV", "production"))

with application.app_context():
    db.create_all()
    try:
        seed_questions_from_file()
    except Exception:
        pass

if __name__ == "__main__":
    from waitress import serve
    port = int(os.environ.get("PORT", 8080))
    print(f"Serving production WSGI with Waitress on http://0.0.0.0:{port}")
    serve(application, host="0.0.0.0", port=port)
