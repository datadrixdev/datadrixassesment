import pytest
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models.assessment import AssessmentAttempt
from app.services.timer_service import check_and_enforce_timer, get_remaining_seconds

def utc_now():
    return datetime.now(timezone.utc)

def test_initial_timer_duration(active_attempt):
    """Assessment is set with exactly 15 minutes duration."""
    remaining = get_remaining_seconds(active_attempt)
    # Remaining seconds should be between 880 and 900
    assert 880 <= remaining <= 900
    assert not active_attempt.is_expired

def test_timer_does_not_reset_on_reconnect(client, candidate_session, active_attempt):
    """Timer remains anchored to server deadline and does not reset on repeated page access."""
    resp1 = client.get(f"/assessment/{active_attempt.id}/status")
    data1 = resp1.get_json()

    # Simulate elapsed time of 5 minutes by shifting deadline backwards
    active_attempt.deadline = utc_now() + timedelta(minutes=10)
    db.session.commit()

    resp2 = client.get(f"/assessment/{active_attempt.id}/status")
    data2 = resp2.get_json()
    assert data2["remaining_seconds"] <= 605

def test_timer_expiration_auto_finalization(app, active_attempt):
    """When the server-authoritative deadline expires, the attempt is finalized automatically."""
    # Set deadline in the past
    active_attempt.deadline = utc_now() - timedelta(minutes=5)
    db.session.commit()

    assert active_attempt.is_expired is True
    expired = check_and_enforce_timer(active_attempt)
    assert expired is True
    assert active_attempt.status == "completed"
    assert active_attempt.end_time is not None

def test_reject_answers_after_deadline(client, candidate_session, active_attempt):
    """Attempting to submit answers after the deadline is rejected by the server."""
    # Expire the deadline
    active_attempt.deadline = utc_now() - timedelta(seconds=10)
    db.session.commit()

    resp = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": "B"}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "expired" in data or "closed" in data.get("error", "").lower()
