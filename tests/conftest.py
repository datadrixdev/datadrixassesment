import os
import pytest
from datetime import datetime, timedelta, timezone
from app import create_app
from app.extensions import db
from app.models.candidate import Candidate
from app.models.assessment import AssessmentAttempt, AttemptQuestion
from app.services.question_service import seed_questions_from_file, generate_questions_for_attempt

def utc_now():
    return datetime.now(timezone.utc)

@pytest.fixture
def app():
    """Create and configure a clean testing application."""
    test_app = create_app("testing")
    with test_app.app_context():
        db.create_all()
        # Seed question bank
        seed_questions_from_file()
        yield test_app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """Test HTTP client."""
    return app.test_client()

@pytest.fixture
def sample_candidate(app):
    """Create a sample candidate in the test database."""
    candidate = Candidate(
        full_name="Jane Doe",
        email="jane.doe@example.com",
        mobile_number="+15551234567"
    )
    db.session.add(candidate)
    db.session.commit()
    return candidate

@pytest.fixture
def candidate_session(client, sample_candidate):
    """Helper to simulate an authenticated candidate session in the test client."""
    with client.session_transaction() as sess:
        sess["candidate_id"] = sample_candidate.id
        sess["candidate_name"] = sample_candidate.full_name
        sess["candidate_email"] = sample_candidate.email
    return sample_candidate

@pytest.fixture
def active_attempt(app, sample_candidate):
    """Create an active assessment attempt with 20 questions."""
    now = utc_now()
    attempt = AssessmentAttempt(
        candidate_id=sample_candidate.id,
        attempt_number=1,
        start_time=now,
        deadline=now + timedelta(minutes=15),
        status="in_progress",
        violation_count=0
    )
    db.session.add(attempt)
    db.session.commit()
    generate_questions_for_attempt(attempt, questions_per_section=5)
    return attempt
