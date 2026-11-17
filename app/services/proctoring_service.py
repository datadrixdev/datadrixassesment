import json
from datetime import datetime, timezone
from app.extensions import db
from app.models.assessment import AssessmentAttempt, AssessmentEvent, ProctoringEvent

def utc_now():
    return datetime.now(timezone.utc)

# Allowlisted proctoring event types
ALLOWLISTED_EVENTS = {
    "MOBILE_PHONE_DETECTED",
    "UNAUTHORIZED_OBJECT_DETECTED",
    "GAZE_AWAY",
    "STATIC_PHOTO_SUSPECTED",
    "HEAD_TURN_LEFT",
    "HEAD_TURN_RIGHT",
    "HEAD_TILT_DOWN",
    "MULTIPLE_FACES_DETECTED",
    "MULTIPLE_PEOPLE_DETECTED",
    "FACE_NOT_DETECTED",
    "FACE_RESTORED",
    "CAMERA_DISCONNECTED",
    "PHONE_DETECTION_UNAVAILABLE"
}

# Vision-based warnings that increment the candidate's vision_warning_count
VISION_WARNING_EVENTS = {
    "MOBILE_PHONE_DETECTED",
    "UNAUTHORIZED_OBJECT_DETECTED",
    "GAZE_AWAY",
    "STATIC_PHOTO_SUSPECTED",
    "HEAD_TURN_LEFT",
    "HEAD_TURN_RIGHT",
    "HEAD_TILT_DOWN",
    "MULTIPLE_FACES_DETECTED",
    "MULTIPLE_PEOPLE_DETECTED"
}

# Standardized warning text per specification
WARNING_MESSAGES = {
    "HEAD_TURN_LEFT": "Head Movement Warning: You appear to be looking to the left. Please keep your head in a comfortable, forward-facing position during the assessment.",
    "HEAD_TURN_RIGHT": "Head Movement Warning: You appear to be looking to the right. Please keep your head in a comfortable, forward-facing position during the assessment.",
    "HEAD_TILT_DOWN": "Head Position Warning: Your head appears to be tilted downward for an extended period. Please return to a comfortable viewing position.",
    "GAZE_AWAY": "Eye Gaze Warning: Your eyes have drifted away from the exam screen for an extended period. Please maintain direct visual focus on your assessment.",
    "MOBILE_PHONE_DETECTED": "Mobile Phone Detected: A mobile phone appears to be visible in your camera view. Please remove it from the camera area and continue the assessment without unauthorized assistance.",
    "UNAUTHORIZED_OBJECT_DETECTED": "Unauthorized Item Detected: An unauthorized item (such as an external screen, book, or notes) was detected in your camera view. Please remove all prohibited materials.",
    "STATIC_PHOTO_SUSPECTED": "Liveness Warning: Camera feed appears static or unresponsive. Please verify that your live webcam is operating properly.",
    "MULTIPLE_FACES_DETECTED": "Multiple Faces Warning: More than one face was detected in camera view. The assessment must be taken alone in a private room without unauthorized individuals.",
    "MULTIPLE_PEOPLE_DETECTED": "Multiple Persons Warning: Another person was detected in your camera view. The assessment must be taken alone in a private room without unauthorized assistance.",
    "FACE_NOT_DETECTED": "Face not clearly detected. Please adjust your camera position and lighting.",
    "FACE_RESTORED": "Face tracking restored. Please maintain your forward-facing posture.",
    "CAMERA_DISCONNECTED": "Camera feed interrupted. Please restore hardware connection.",
    "PHONE_DETECTION_UNAVAILABLE": "Mobile phone detection is currently unavailable on this device."
}

# Configurable cooldown in seconds to prevent spamming duplicate events
COOLDOWN_WINDOW_SECONDS = 3.0

def validate_proctoring_payload(data):
    """
    Validates incoming proctoring event payload against constraints and allowlists.
    Returns (is_valid: bool, error: str, cleaned_data: dict)
    """
    if not isinstance(data, dict):
        return False, "Payload must be a valid JSON object.", {}

    event_type = data.get("event_type")
    if not event_type or not isinstance(event_type, str):
        return False, "Missing or invalid 'event_type'.", {}

    event_type = event_type.strip().upper()
    if event_type not in ALLOWLISTED_EVENTS:
        return False, f"Unsupported event type: '{event_type}'. Must be one of {sorted(list(ALLOWLISTED_EVENTS))}.", {}

    confidence = data.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
            if confidence < 0.0 or confidence > 1.0:
                return False, "Confidence score must be between 0.0 and 1.0.", {}
        except (ValueError, TypeError):
            return False, "Confidence score must be a numerical float between 0.0 and 1.0.", {}

    duration_ms = data.get("duration_ms")
    if duration_ms is not None:
        try:
            duration_ms = int(duration_ms)
            if duration_ms < 0:
                return False, "Duration (duration_ms) must be a non-negative integer.", {}
        except (ValueError, TypeError):
            return False, "Duration (duration_ms) must be an integer.", {}

    client_event_id = data.get("client_event_id")
    if client_event_id is not None:
        if not isinstance(client_event_id, str):
            client_event_id = str(client_event_id)
        client_event_id = client_event_id.strip()[:100]

    metadata = data.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        metadata = {"raw": str(metadata)}

    return True, None, {
        "event_type": event_type,
        "confidence": confidence,
        "duration_ms": duration_ms,
        "client_event_id": client_event_id,
        "metadata": metadata or {}
    }

def record_proctoring_event(attempt, payload):
    """
    Records a structured browser-based proctoring event into the database with deduplication,
    rate-limiting, separate counter tracking, and audit trail creation.
    """
    now = utc_now()
    event_type = payload["event_type"]
    confidence = payload.get("confidence")
    duration_ms = payload.get("duration_ms")
    client_event_id = payload.get("client_event_id")
    metadata = payload.get("metadata", {})

    # 1. Deduplication by client_event_id
    if client_event_id:
        existing_event = ProctoringEvent.query.filter_by(
            attempt_id=attempt.id,
            client_event_id=client_event_id
        ).first()
        if existing_event:
            return {
                "success": True,
                "status": "deduplicated",
                "action": "none",
                "event_id": existing_event.id,
                "event_type": existing_event.event_type,
                "vision_warning_count": attempt.vision_warning_count,
                "navigation_violation_count": attempt.violation_count,
                "message": "Event with this client ID was already recorded."
            }

    # 2. Rate limiting & cooldown window per event_type
    last_event = ProctoringEvent.query.filter_by(
        attempt_id=attempt.id,
        event_type=event_type
    ).order_by(ProctoringEvent.timestamp.desc()).first()

    if last_event:
        last_time = last_event.timestamp.replace(tzinfo=timezone.utc) if last_event.timestamp.tzinfo is None else last_event.timestamp
        time_elapsed = (now - last_time).total_seconds()
        if time_elapsed < COOLDOWN_WINDOW_SECONDS:
            return {
                "success": True,
                "status": "debounced",
                "action": "none",
                "event_id": last_event.id,
                "event_type": last_event.event_type,
                "vision_warning_count": attempt.vision_warning_count,
                "navigation_violation_count": attempt.violation_count,
                "message": f"Event debounced within {COOLDOWN_WINDOW_SECONDS}s cooldown."
            }

    # 3. Vision warning counter tracking (separate from navigation violation count)
    if event_type in VISION_WARNING_EVENTS:
        attempt.vision_warning_count = (attempt.vision_warning_count or 0) + 1

    # 4. Persist in ProctoringEvent table
    proctor_event = ProctoringEvent(
        attempt_id=attempt.id,
        event_type=event_type,
        confidence=confidence,
        duration_ms=duration_ms,
        client_event_id=client_event_id,
        metadata_json=json.dumps(metadata) if metadata else None,
        timestamp=now
    )
    db.session.add(proctor_event)

    # 5. Mirror into AssessmentEvent for unified session audit trail
    audit_meta = dict(metadata)
    audit_meta.update({
        "confidence": confidence,
        "duration_ms": duration_ms,
        "client_event_id": client_event_id,
        "vision_warning_count": attempt.vision_warning_count
    })
    assessment_event = AssessmentEvent(
        attempt_id=attempt.id,
        event_type=f"PROCTOR_{event_type}",
        timestamp=now,
        metadata_json=json.dumps(audit_meta)
    )
    db.session.add(assessment_event)
    db.session.commit()

    warning_msg = WARNING_MESSAGES.get(event_type, f"Proctoring alert: {event_type}")

    return {
        "success": True,
        "status": "recorded",
        "action": "logged",
        "event_id": proctor_event.id,
        "event_type": proctor_event.event_type,
        "confidence": proctor_event.confidence,
        "duration_ms": proctor_event.duration_ms,
        "vision_warning_count": attempt.vision_warning_count,
        "navigation_violation_count": attempt.violation_count,
        "warning_message": warning_msg,
        "is_vision_warning": event_type in VISION_WARNING_EVENTS
    }
