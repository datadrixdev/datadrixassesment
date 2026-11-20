import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv(".env", override=True)

class Config:
    """Base application configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "super-secret-production-key-change-in-env-982348")
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    # For Vercel or serverless environments, fallback SQLite to writable /tmp directory if DATABASE_URL is not set
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        default_db_path = "/tmp/assessment.db"
    else:
        default_db_path = os.path.join(BASE_DIR, "assessment.db")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{default_db_path}"
    )
    # Fix for Heroku/Render Postgres URL scheme if needed
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ASSESSMENT_DURATION_MINUTES = 15
    MAX_VIOLATIONS_BEFORE_ABORT = 2
    QUESTIONS_PER_SECTION = 5
    TOTAL_QUESTIONS = 20
    
    # Session & Security (Configured for embedded iframe assessment portal)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "None"
    SESSION_COOKIE_SECURE = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    WTF_CSRF_ENABLED = False
    WTF_CSRF_CHECK_DEFAULT = False
    WTF_CSRF_TIME_LIMIT = None

    # Email / SMTP Configuration
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "True").lower() in ("true", "1")
    SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "False").lower() in ("true", "1")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "Datadrix Assessments <datadrix@gmail.com>")
    MAIL_SAVE_LOCAL_COPY = os.environ.get("MAIL_SAVE_LOCAL_COPY", "True").lower() in ("true", "1")
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
    ADMIN_LEAD_EMAIL = os.environ.get("ADMIN_LEAD_EMAIL", "datadrix@gmail.com")

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SESSION_COOKIE_SECURE = True

class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = "test-secret-key-12345"
    SMTP_SERVER = ""

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SESSION_COOKIE_SECURE = True

config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig
}
