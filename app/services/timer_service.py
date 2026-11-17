import json
from datetime import datetime, timezone
from app.extensions import db
from app.models.assessment import AssessmentEvent
from app.services.scoring_service import finalize_and_score_attempt

def utc_now():
    return datetime.now(timezone.utc)

def check_and_enforce_timer(attempt):
    """
    Checks if the assessment attempt deadline has elapsed.
    If elapsed and attempt is still in_progress, automatically finalizes and scores it.
    Returns True if expired, False otherwise.
    """
    if attempt.status != "in_progress":
        return attempt.status in ["completed", "aborted"]

    now = utc_now()
    deadline = attempt.deadline.replace(tzinfo=timezone.utc) if attempt.deadline.tzinfo is None else attempt.deadline

    if now >= deadline:
        # Time expired: log event and finalize attempt
        event = AssessmentEvent(
            attempt_id=attempt.id,
            event_type="TIME_EXPIRED",
            timestamp=now,
            metadata_json=json.dumps({"reason": "Timer reached zero, server auto-finalized"})
        )
        db.session.add(event)
        db.session.commit()

        finalize_and_score_attempt(attempt.id)
        return True

    return False

def get_remaining_seconds(attempt):
    """Returns the remaining seconds based on the server-authoritative deadline."""
    now = utc_now()
    deadline = attempt.deadline.replace(tzinfo=timezone.utc) if attempt.deadline.tzinfo is None else attempt.deadline
    diff = (deadline - now).total_seconds()
    return max(0, int(diff))
