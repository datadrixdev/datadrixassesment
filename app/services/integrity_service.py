import json
from datetime import datetime, timezone
from app.extensions import db
from app.models.assessment import AssessmentAttempt, AssessmentEvent

def utc_now():
    return datetime.now(timezone.utc)

DEBOUNCE_WINDOW_SECONDS = 2.0

def record_violation(attempt, event_type, metadata=None):
    """
    Records a screen-switching integrity violation with debouncing and applies the two-strike policy.
    Strike 1: Warning issued, attempt continues.
    Strike 2: Attempt aborted immediately.
    """
    if attempt.status != "in_progress":
        return {
            "action": "none",
            "violation_count": attempt.violation_count,
            "status": attempt.status,
            "message": f"Assessment is already {attempt.status}."
        }

    now = utc_now()

    # Check for rapid duplicate fires within DEBOUNCE_WINDOW_SECONDS
    last_violation_event = AssessmentEvent.query.filter(
        AssessmentEvent.attempt_id == attempt.id,
        AssessmentEvent.event_type.in_(["VIOLATION_WARNING", "VIOLATION_ABORT"])
    ).order_by(AssessmentEvent.timestamp.desc()).first()

    if last_violation_event:
        last_time = last_violation_event.timestamp.replace(tzinfo=timezone.utc) if last_violation_event.timestamp.tzinfo is None else last_violation_event.timestamp
        time_since_last = (now - last_time).total_seconds()
        if time_since_last < DEBOUNCE_WINDOW_SECONDS:
            # Debounced duplicate event
            return {
                "action": "debounced",
                "violation_count": attempt.violation_count,
                "status": attempt.status,
                "message": "Duplicate violation event debounced."
            }

    # Increment violation count
    attempt.violation_count += 1
    meta_dict = metadata or {}
    meta_dict["event_type_reported"] = event_type
    meta_dict["violation_count"] = attempt.violation_count

    if attempt.violation_count == 1:
        # First strike: Warning
        event = AssessmentEvent(
            attempt_id=attempt.id,
            event_type="VIOLATION_WARNING",
            timestamp=now,
            metadata_json=json.dumps(meta_dict)
        )
        db.session.add(event)
        db.session.commit()
        return {
            "action": "warning",
            "violation_count": 1,
            "status": "in_progress",
            "message": "Warning 1 of 2: Leaving the assessment window or switching tabs is strictly prohibited. A second violation will automatically terminate your exam."
        }
    else:
        # Second strike: Immediate Abort
        attempt.status = "aborted"
        attempt.end_time = now
        event = AssessmentEvent(
            attempt_id=attempt.id,
            event_type="VIOLATION_ABORT",
            timestamp=now,
            metadata_json=json.dumps(meta_dict)
        )
        db.session.add(event)
        db.session.commit()
        return {
            "action": "aborted",
            "violation_count": attempt.violation_count,
            "status": "aborted",
            "redirect_url": f"/aborted/{attempt.id}",
            "message": "Assessment aborted due to multiple integrity violations. Your attempt has been voided."
        }

def record_device_event(attempt, event_name, metadata=None):
    """
    Log device-related events (e.g. camera/microphone disconnected or restored).
    These do not trigger screen-switching strike counts but are audited.
    """
    now = utc_now()
    event = AssessmentEvent(
        attempt_id=attempt.id,
        event_type=event_name,
        timestamp=now,
        metadata_json=json.dumps(metadata or {})
    )
    db.session.add(event)
    db.session.commit()
    return {"status": "recorded"}
