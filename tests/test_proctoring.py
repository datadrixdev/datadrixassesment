import pytest
import json
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models.candidate import Candidate
from app.models.assessment import AssessmentAttempt, ProctoringEvent, AssessmentEvent
from app.services.proctoring_service import (
    ALLOWLISTED_EVENTS,
    VISION_WARNING_EVENTS,
    validate_proctoring_payload,
    record_proctoring_event
)

def utc_now():
    return datetime.now(timezone.utc)

@pytest.fixture
def proctor_session(client, app):
    """Sets up an authenticated candidate and active assessment attempt."""
    with app.app_context():
        candidate = Candidate(
            full_name="Proctor Test Candidate",
            email="proctor.test@example.com",
            mobile_number="+91 9988776655"
        )
        db.session.add(candidate)
        db.session.commit()

        now = utc_now()
        attempt = AssessmentAttempt(
            candidate_id=candidate.id,
            attempt_number=1,
            start_time=now,
            deadline=now + timedelta(minutes=15),
            status="in_progress",
            violation_count=0,
            vision_warning_count=0,
            score=0,
            max_score=20,
            unanswered_count=20
        )
        db.session.add(attempt)
        db.session.commit()

        candidate_id = candidate.id
        attempt_id = attempt.id

    with client.session_transaction() as sess:
        sess["candidate_id"] = candidate_id
        sess["candidate_name"] = "Proctor Test Candidate"
        sess["candidate_email"] = "proctor.test@example.com"

    return {"candidate_id": candidate_id, "attempt_id": attempt_id}

def test_payload_validator_allowlist():
    """Verify validation of allowlisted proctoring events."""
    for event_type in ALLOWLISTED_EVENTS:
        payload = {
            "event_type": event_type,
            "confidence": 0.85,
            "duration_ms": 2500,
            "client_event_id": f"test-{event_type}"
        }
        is_valid, err, cleaned = validate_proctoring_payload(payload)
        assert is_valid is True, f"Failed for {event_type}: {err}"
        assert cleaned["event_type"] == event_type
        assert cleaned["confidence"] == 0.85
        assert cleaned["duration_ms"] == 2500

def test_payload_validator_invalid_types():
    """Verify unsupported event types are rejected."""
    bad_payload = {"event_type": "UNKNOWN_ARBITRARY_EVENT"}
    is_valid, err, _ = validate_proctoring_payload(bad_payload)
    assert is_valid is False
    assert "Unsupported event type" in err

def test_payload_validator_confidence_bounds():
    """Verify confidence must be between 0.0 and 1.0."""
    # Out of range > 1.0
    is_valid, err, _ = validate_proctoring_payload({"event_type": "HEAD_TURN_LEFT", "confidence": 1.5})
    assert is_valid is False
    assert "between 0.0 and 1.0" in err

    # Out of range < 0.0
    is_valid, err, _ = validate_proctoring_payload({"event_type": "HEAD_TURN_LEFT", "confidence": -0.1})
    assert is_valid is False
    assert "between 0.0 and 1.0" in err

    # Non-numeric
    is_valid, err, _ = validate_proctoring_payload({"event_type": "HEAD_TURN_LEFT", "confidence": "high"})
    assert is_valid is False

def test_payload_validator_duration_bounds():
    """Verify duration_ms must be a non-negative integer."""
    is_valid, err, _ = validate_proctoring_payload({"event_type": "HEAD_TURN_LEFT", "duration_ms": -100})
    assert is_valid is False
    assert "non-negative integer" in err

def test_api_proctoring_event_success(client, app, proctor_session):
    """POST /api/assessment/<id>/proctoring-event successfully logs event."""
    attempt_id = proctor_session["attempt_id"]
    payload = {
        "event_type": "HEAD_TURN_LEFT",
        "confidence": 0.92,
        "duration_ms": 2600,
        "client_event_id": "event-12345"
    }
    resp = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["event_type"] == "HEAD_TURN_LEFT"
    assert data["vision_warning_count"] == 1
    assert "looking to the left" in data["warning_message"]

    # Verify database persistence
    with app.app_context():
        p_event = ProctoringEvent.query.filter_by(client_event_id="event-12345").first()
        assert p_event is not None
        assert p_event.event_type == "HEAD_TURN_LEFT"
        assert p_event.confidence == 0.92
        assert p_event.duration_ms == 2600

        # Verify mirrored in AssessmentEvent
        a_event = AssessmentEvent.query.filter_by(attempt_id=attempt_id, event_type="PROCTOR_HEAD_TURN_LEFT").first()
        assert a_event is not None

def test_api_proctoring_event_client_id_deduplication(client, proctor_session):
    """Duplicate client_event_id returns deduplicated status without duplicate database row."""
    attempt_id = proctor_session["attempt_id"]
    payload = {
        "event_type": "MOBILE_PHONE_DETECTED",
        "confidence": 0.88,
        "duration_ms": 3000,
        "client_event_id": "phone-dedup-unique-id"
    }
    # First call
    resp1 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json=payload)
    assert resp1.status_code == 200
    assert resp1.get_json()["status"] == "recorded"
    assert resp1.get_json()["vision_warning_count"] == 1

    # Second call with same client_event_id
    resp2 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json=payload)
    assert resp2.status_code == 200
    assert resp2.get_json()["status"] == "deduplicated"
    assert resp2.get_json()["vision_warning_count"] == 1  # Not double-counted!

def test_api_proctoring_event_cooldown_rate_limiting(client, proctor_session):
    """Firing identical event type within cooldown window is debounced."""
    attempt_id = proctor_session["attempt_id"]
    # Event 1 without client_id
    resp1 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "HEAD_TURN_RIGHT",
        "confidence": 0.89,
        "duration_ms": 2200
    })
    assert resp1.status_code == 200
    assert resp1.get_json()["status"] == "recorded"
    assert resp1.get_json()["vision_warning_count"] == 1

    # Immediate second event of same type
    resp2 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "HEAD_TURN_RIGHT",
        "confidence": 0.91,
        "duration_ms": 2400
    })
    assert resp2.status_code == 200
    assert resp2.get_json()["status"] == "debounced"
    assert resp2.get_json()["vision_warning_count"] == 1  # Not incremented while debounced

def test_vision_warnings_do_not_abort_test(client, app, proctor_session):
    """Multiple vision warnings log incidents and increment vision_warning_count, but do NOT abort test."""
    attempt_id = proctor_session["attempt_id"]

    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, attempt_id)
        # Directly test recording multiple distinct vision events
        record_proctoring_event(attempt, {"event_type": "MOBILE_PHONE_DETECTED", "client_event_id": "p1"})
        record_proctoring_event(attempt, {"event_type": "HEAD_TURN_LEFT", "client_event_id": "h1"})
        record_proctoring_event(attempt, {"event_type": "HEAD_TURN_RIGHT", "client_event_id": "h2"})
        record_proctoring_event(attempt, {"event_type": "HEAD_TILT_DOWN", "client_event_id": "h3"})
        record_proctoring_event(attempt, {"event_type": "MULTIPLE_FACES_DETECTED", "client_event_id": "mf1"})
        record_proctoring_event(attempt, {"event_type": "MULTIPLE_PEOPLE_DETECTED", "client_event_id": "mp1"})

        assert attempt.vision_warning_count == 6
        assert attempt.violation_count == 0  # Separate counter untouched!
        assert attempt.status == "in_progress"  # Not aborted!

def test_api_proctoring_event_unauthorized_session(client, proctor_session):
    """Request without session candidate_id returns 401 Unauthorized."""
    attempt_id = proctor_session["attempt_id"]
    with client.session_transaction() as sess:
        sess.clear()

    resp = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={"event_type": "HEAD_TURN_LEFT"})
    assert resp.status_code == 401

def test_api_proctoring_event_cross_candidate_forbidden(client, app, proctor_session):
    """Request by candidate A on candidate B's attempt returns 403 Forbidden."""
    attempt_id = proctor_session["attempt_id"]
    with app.app_context():
        other_candidate = Candidate(
            full_name="Impostor",
            email="impostor@example.com",
            mobile_number="+91 1234567890"
        )
        db.session.add(other_candidate)
        db.session.commit()
        other_id = other_candidate.id

    with client.session_transaction() as sess:
        sess["candidate_id"] = other_id

    resp = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={"event_type": "HEAD_TURN_LEFT"})
    assert resp.status_code == 403

def test_api_proctoring_event_completed_attempt_rejected(client, app, proctor_session):
    """Completed assessment rejects incoming proctoring events."""
    attempt_id = proctor_session["attempt_id"]
    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, attempt_id)
        attempt.status = "completed"
        db.session.commit()

    resp = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={"event_type": "HEAD_TURN_LEFT"})
    assert resp.status_code == 400
    assert "completed" in resp.get_json()["error"]

def test_api_proctoring_event_expired_attempt_rejected(client, app, proctor_session):
    """Expired timer rejects incoming proctoring events."""
    attempt_id = proctor_session["attempt_id"]
    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, attempt_id)
        # Push deadline into past
        attempt.deadline = utc_now() - timedelta(minutes=5)
        db.session.commit()

    resp = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={"event_type": "HEAD_TURN_LEFT"})
    assert resp.status_code == 400
    assert "expired" in resp.get_json()["error"].lower()

def test_phone_detection_unavailable_event(client, proctor_session):
    """PHONE_DETECTION_UNAVAILABLE logs successfully without incrementing vision_warning_count."""
    attempt_id = proctor_session["attempt_id"]
    resp = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "PHONE_DETECTION_UNAVAILABLE",
        "client_event_id": "phone-unavail-test"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["event_type"] == "PHONE_DETECTION_UNAVAILABLE"
    assert data["vision_warning_count"] == 0  # Informational only, not a warning!
    assert data["is_vision_warning"] is False

def test_face_not_detected_and_restored_events(client, proctor_session):
    """FACE_NOT_DETECTED and FACE_RESTORED log correctly with appropriate warning text."""
    attempt_id = proctor_session["attempt_id"]
    resp1 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "FACE_NOT_DETECTED",
        "duration_ms": 3000,
        "client_event_id": "face-missing-1"
    })
    assert resp1.status_code == 200
    assert "Face not clearly detected" in resp1.get_json()["warning_message"]

    resp2 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "FACE_RESTORED",
        "client_event_id": "face-restored-1"
    })
    assert resp2.status_code == 200
    assert "restored" in resp2.get_json()["warning_message"].lower()

def test_proctoring_does_not_modify_scores(client, app, proctor_session):
    """Verify that proctoring events strictly do not mutate candidate score or answer state."""
    attempt_id = proctor_session["attempt_id"]
    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, attempt_id)
        attempt.score = 15
        db.session.commit()

    resp = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "MOBILE_PHONE_DETECTED",
        "confidence": 0.95,
        "duration_ms": 2500,
        "client_event_id": "score-integrity-check"
    })
    assert resp.status_code == 200

    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, attempt_id)
        assert attempt.score == 15
        assert attempt.max_score == 20
        assert attempt.vision_warning_count == 1

def test_gaze_deviation_and_prohibited_objects_events(client, proctor_session):
    """Verify GAZE_AWAY, UNAUTHORIZED_OBJECT_DETECTED, and STATIC_PHOTO_SUSPECTED log properly."""
    attempt_id = proctor_session["attempt_id"]

    # 1. Gaze Away
    resp1 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "GAZE_AWAY",
        "confidence": 0.92,
        "duration_ms": 3200,
        "client_event_id": "gaze-test-1"
    })
    assert resp1.status_code == 200
    d1 = resp1.get_json()
    assert d1["success"] is True
    assert "gaze" in d1["warning_message"].lower() or "eyes" in d1["warning_message"].lower()
    assert d1["vision_warning_count"] == 1

    # 2. Unauthorized Object (Book / Secondary Display)
    resp2 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "UNAUTHORIZED_OBJECT_DETECTED",
        "confidence": 0.94,
        "duration_ms": 2500,
        "client_event_id": "object-test-1"
    })
    assert resp2.status_code == 200
    d2 = resp2.get_json()
    assert d2["success"] is True
    assert "unauthorized" in d2["warning_message"].lower() or "item" in d2["warning_message"].lower()
    assert d2["vision_warning_count"] == 2

    # 3. Static Photo Suspected
    resp3 = client.post(f"/api/assessment/{attempt_id}/proctoring-event", json={
        "event_type": "STATIC_PHOTO_SUSPECTED",
        "confidence": 0.88,
        "duration_ms": 26000,
        "client_event_id": "static-photo-test-1"
    })
    assert resp3.status_code == 200
    d3 = resp3.get_json()
    assert d3["success"] is True
    assert "liveness" in d3["warning_message"].lower() or "static" in d3["warning_message"].lower()
    assert d3["vision_warning_count"] == 3


