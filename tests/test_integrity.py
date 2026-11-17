import time
import pytest
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models.assessment import AssessmentAttempt, AssessmentEvent
from app.services.integrity_service import record_violation, record_device_event

def utc_now():
    return datetime.now(timezone.utc)

def test_first_violation_triggers_warning(app, active_attempt):
    """First screen-switching incident records strike 1 warning and keeps attempt in_progress."""
    result = record_violation(active_attempt, "tab_switch", {"test": True})
    assert result["action"] == "warning"
    assert result["violation_count"] == 1
    assert active_attempt.status == "in_progress"

    # Verify event log
    event = AssessmentEvent.query.filter_by(attempt_id=active_attempt.id, event_type="VIOLATION_WARNING").first()
    assert event is not None

def test_violation_debouncing(app, active_attempt):
    """Violations fired within the debounce window do not increment strike counter."""
    res1 = record_violation(active_attempt, "window_blur")
    assert res1["action"] == "warning"
    assert res1["violation_count"] == 1

    # Immediate second fire within milliseconds
    res2 = record_violation(active_attempt, "tab_switch")
    assert res2["action"] == "debounced"
    assert res2["violation_count"] == 1
    assert active_attempt.status == "in_progress"

def test_second_violation_triggers_abort(app, active_attempt):
    """Second screen-switching incident terminates and aborts the assessment attempt."""
    # First violation
    record_violation(active_attempt, "tab_switch")

    # Shift last violation event timestamp backwards by 3 seconds to bypass debounce
    last_event = AssessmentEvent.query.filter_by(attempt_id=active_attempt.id).first()
    last_event.timestamp = utc_now() - timedelta(seconds=3)
    db.session.commit()

    # Second violation
    res = record_violation(active_attempt, "tab_switch")
    assert res["action"] == "aborted"
    assert res["violation_count"] == 2
    assert active_attempt.status == "aborted"
    assert active_attempt.end_time is not None

    # Verify abort event log
    abort_event = AssessmentEvent.query.filter_by(attempt_id=active_attempt.id, event_type="VIOLATION_ABORT").first()
    assert abort_event is not None

def test_aborted_attempt_routes(client, candidate_session, active_attempt):
    """Accessing an aborted attempt redirects to the aborted view."""
    active_attempt.status = "aborted"
    active_attempt.violation_count = 2
    db.session.commit()

    # GET /assessment/<id> should redirect to /aborted/<id>
    resp = client.get(f"/assessment/{active_attempt.id}", follow_redirects=False)
    assert resp.status_code == 302
    assert f"/aborted/{active_attempt.id}" in resp.headers["Location"]

    # View aborted page
    resp_aborted = client.get(f"/aborted/{active_attempt.id}")
    assert resp_aborted.status_code == 200
    assert "Aborted" in resp_aborted.data.decode("utf-8")
    assert "Integrity Policy Violation" in resp_aborted.data.decode("utf-8")

def test_retake_after_abort(client, candidate_session, active_attempt):
    """Candidate can initiate a fresh retake following an aborted attempt."""
    active_attempt.status = "aborted"
    active_attempt.violation_count = 2
    db.session.commit()

    resp = client.post(f"/assessment/{active_attempt.id}/retake", follow_redirects=False)
    assert resp.status_code == 302

    # Verify new attempt was created
    new_attempt = AssessmentAttempt.query.filter_by(
        candidate_id=active_attempt.candidate_id,
        attempt_number=2
    ).first()
    assert new_attempt is not None
    assert new_attempt.id != active_attempt.id
    assert new_attempt.status == "in_progress"
    assert new_attempt.violation_count == 0
    assert len(new_attempt.attempt_questions) == 20
    assert resp.headers["Location"] == f"/assessment/{new_attempt.id}"

def test_device_event_logging_does_not_abort(app, active_attempt):
    """Hardware device disconnects are logged separately without counting as screen-switch strikes."""
    res = record_device_event(active_attempt, "DEVICE_DISCONNECTED", {"track": "video"})
    assert res["status"] == "recorded"
    assert active_attempt.violation_count == 0
    assert active_attempt.status == "in_progress"

    event = AssessmentEvent.query.filter_by(attempt_id=active_attempt.id, event_type="DEVICE_DISCONNECTED").first()
    assert event is not None

def test_clipboard_attempt_logged(client, candidate_session, active_attempt):
    """Clipboard actions (copy, cut, paste) are blocked and logged without triggering screen strike."""
    resp = client.post(
        f"/api/assessment/{active_attempt.id}/violation",
        json={"eventType": "clipboard_attempt", "metadata": {"action": "copy"}}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "clipboard_blocked_logged"
    assert data["action"] == "none"

    # Verify attempt is still in progress and strikes did not increment
    assert active_attempt.violation_count == 0
    assert active_attempt.status == "in_progress"

    # Verify event logged in audit trail
    event = AssessmentEvent.query.filter_by(attempt_id=active_attempt.id, event_type="CLIPBOARD_BLOCKED").first()
    assert event is not None
