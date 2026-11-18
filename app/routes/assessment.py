import json
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, abort, flash, current_app
from app.extensions import db
from app.models.candidate import Candidate
from app.models.assessment import AssessmentAttempt, AttemptQuestion, AssessmentEvent
from app.services.question_service import generate_questions_for_attempt, get_candidate_assessment_payload
from app.services.scoring_service import finalize_and_score_attempt
from app.services.timer_service import check_and_enforce_timer, get_remaining_seconds
from app.services.integrity_service import record_violation, record_device_event

assessment_bp = Blueprint("assessment", __name__)

def utc_now():
    return datetime.now(timezone.utc)

def verify_candidate_attempt(attempt_id):
    """Ensure candidate is in session and owns the requested attempt."""
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return None, (jsonify({"error": "Unauthorized session."}), 401)

    attempt = db.session.get(AssessmentAttempt, attempt_id)
    if not attempt:
        from app.services.rehydration_service import rehydrate_attempt_if_needed
        attempt = rehydrate_attempt_if_needed(attempt_id)

    if not attempt:
        return None, (jsonify({"error": "Assessment attempt not found."}), 404)

    if attempt.candidate_id != candidate_id:
        return None, (jsonify({"error": "Forbidden: You do not have permission to access this attempt."}), 403)

    return attempt, None

@assessment_bp.route("/assessment", methods=["GET"])
def assessment_index():
    """Redirect to the active in-progress attempt, device check, or home screen."""
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return redirect(url_for("main.index"))

    # Find the most recent active attempt
    active_attempt = AssessmentAttempt.query.filter_by(
        candidate_id=candidate_id,
        status="in_progress"
    ).order_by(AssessmentAttempt.start_time.desc()).first()

    if active_attempt:
        return redirect(url_for("assessment.assessment_view", attempt_id=active_attempt.id))

    # If no active in-progress attempt, redirect to device check
    return redirect(url_for("main.device_check"))

@assessment_bp.route("/assessment/start", methods=["POST"])
def start_assessment():
    """Create a secure timed attempt with 20 randomized questions and redirect to the test screen."""
    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return redirect(url_for("main.index"))

    candidate = db.session.get(Candidate, candidate_id)
    if not candidate:
        return redirect(url_for("main.index"))

    # Check retake cooldown if candidate previously completed an assessment
    from app.services.discount_service import get_candidate_previous_history
    history = get_candidate_previous_history(candidate.id)
    bypass_cooldown = request.form.get("bypass_cooldown") == "1" or request.args.get("force") == "1"
    if history["has_previous_attempt"] and history["cooldown_active"] and not bypass_cooldown:
        flash(f"Retake Cooldown: You can retake this assessment in {history['hours_remaining']} hours and {history['minutes_remaining']} minutes.", "warning")
        return redirect(url_for("main.device_check"))

    # Count prior attempts
    prior_count = AssessmentAttempt.query.filter_by(candidate_id=candidate.id).count()

    now = utc_now()
    duration_min = current_app.config.get("ASSESSMENT_DURATION_MINUTES", 15)
    deadline = now + timedelta(minutes=duration_min)

    attempt = AssessmentAttempt(
        candidate_id=candidate.id,
        attempt_number=prior_count + 1,
        start_time=now,
        deadline=deadline,
        status="in_progress",
        violation_count=0,
        vision_warning_count=0,
        score=0,
        max_score=20,
        unanswered_count=20
    )
    db.session.add(attempt)
    db.session.commit()

    # Generate 5 questions per section (20 total)
    attempt_questions = generate_questions_for_attempt(attempt, questions_per_section=5)

    # Store assigned questions and attempt metadata in session for serverless resilience
    session["assigned_question_codes"] = [aq.question.code for aq in attempt_questions]
    session["attempt_id"] = attempt.id
    session["attempt_number"] = attempt.attempt_number
    session.permanent = True

    # Log session start
    event = AssessmentEvent(
        attempt_id=attempt.id,
        event_type="SESSION_STARTED",
        timestamp=now,
        metadata_json=json.dumps({"attempt_number": attempt.attempt_number})
    )
    db.session.add(event)
    db.session.commit()

    return redirect(url_for("assessment.assessment_view", attempt_id=attempt.id))

@assessment_bp.route("/assessment/<attempt_id>", methods=["GET"])
def assessment_view(attempt_id):
    """Render the active distraction-free assessment screen."""
    attempt, err = verify_candidate_attempt(attempt_id)
    if err:
        return err

    # Check status redirections
    if attempt.status == "aborted":
        return redirect(url_for("results.aborted_view", attempt_id=attempt.id))
    if attempt.status == "completed":
        return redirect(url_for("results.result_view", attempt_id=attempt.id))

    # Check if server-authoritative timer has expired
    if check_and_enforce_timer(attempt):
        return redirect(url_for("results.result_view", attempt_id=attempt.id))

    remaining_sec = get_remaining_seconds(attempt)
    questions = get_candidate_assessment_payload(attempt)

    return render_template(
        "assessment.html",
        attempt=attempt,
        questions=questions,
        remaining_seconds=remaining_sec,
        candidate_name=session.get("candidate_name", "Candidate")
    )

@assessment_bp.route("/api/assessment/<attempt_id>/answer", methods=["POST"])
def save_answer(attempt_id):
    """Save or update candidate's answer or review flag asynchronously."""
    attempt, err = verify_candidate_attempt(attempt_id)
    if err:
        return err

    if attempt.status != "in_progress":
        return jsonify({"error": f"Cannot modify answer: attempt is {attempt.status}."}), 400

    if check_and_enforce_timer(attempt):
        return jsonify({"error": "Assessment time has expired. Submissions are closed.", "expired": True}), 400

    data = request.get_json() or {}
    order = data.get("question_order")
    selected_option = data.get("selected_option")  # "A", "B", "C", "D" or None
    is_marked_for_review = data.get("is_marked_for_review")

    if not order or not isinstance(order, int) or order < 1 or order > 20:
        return jsonify({"error": "Invalid question order."}), 400

    if selected_option is not None and selected_option not in ["A", "B", "C", "D"]:
        return jsonify({"error": "Invalid option selected."}), 400

    aq = AttemptQuestion.query.filter_by(attempt_id=attempt.id, question_order=order).first()
    if not aq:
        return jsonify({"error": "Question not found in attempt."}), 404

    # Update answer
    if "selected_option" in data:
        aq.selected_option = selected_option
        aq.answered_at = utc_now() if selected_option is not None else None

    if "is_marked_for_review" in data:
        aq.is_marked_for_review = bool(is_marked_for_review)

    db.session.commit()

    return jsonify({
        "success": True,
        "question_order": aq.question_order,
        "selected_option": aq.selected_option,
        "is_marked_for_review": aq.is_marked_for_review
    })

@assessment_bp.route("/api/assessment/<attempt_id>/violation", methods=["POST"])
def report_violation(attempt_id):
    """Record an integrity event and enforce the two-strike policy."""
    attempt, err = verify_candidate_attempt(attempt_id)
    if err:
        return err

    data = request.get_json() or {}
    event_type = data.get("eventType", "tab_switch")
    metadata = data.get("metadata", {})

    if event_type == "device_disconnected":
        record_device_event(attempt, "DEVICE_DISCONNECTED", metadata)
        return jsonify({"status": "device_warning_logged", "action": "none"})

    if event_type == "device_restored":
        record_device_event(attempt, "DEVICE_RESTORED", metadata)
        return jsonify({"status": "device_restored_logged", "action": "none"})

    if event_type == "clipboard_attempt":
        record_device_event(attempt, "CLIPBOARD_BLOCKED", metadata)
        return jsonify({"status": "clipboard_blocked_logged", "action": "none"})

    # Screen switching / tab blur / fullscreen exit violation
    result = record_violation(attempt, event_type, metadata)
    return jsonify(result)

@assessment_bp.route("/api/assessment/<attempt_id>/proctoring-event", methods=["POST"])
def receive_proctoring_event(attempt_id):
    """
    Accept validated browser-based AI vision proctoring detections.
    Supports mobile phone detection, head-pose estimation (yaw/pitch), and hardware indicators.
    """
    attempt, err = verify_candidate_attempt(attempt_id)
    if err:
        return err

    if attempt.status != "in_progress":
        return jsonify({"error": f"Cannot submit proctoring event: assessment is {attempt.status}."}), 400

    if check_and_enforce_timer(attempt):
        return jsonify({"error": "Assessment time has expired.", "expired": True}), 400

    raw_data = request.get_json()
    if raw_data is None:
        return jsonify({"error": "Invalid request body: JSON required."}), 400

    from app.services.proctoring_service import validate_proctoring_payload, record_proctoring_event
    is_valid, validation_err, cleaned_payload = validate_proctoring_payload(raw_data)
    if not is_valid:
        return jsonify({"error": validation_err}), 400

    result = record_proctoring_event(attempt, cleaned_payload)
    return jsonify(result), 200

@assessment_bp.route("/api/assessment/<attempt_id>/submit", methods=["POST"])
def submit_assessment(attempt_id):
    """Finalize the assessment, score answers, and return result redirect."""
    raw_payload = request.get_json(silent=True) or {}
    answers_payload = raw_payload.get("answers", [])

    from app.services.rehydration_service import rehydrate_attempt_if_needed, _apply_answers_payload
    attempt = db.session.get(AssessmentAttempt, attempt_id)
    if not attempt:
        attempt = rehydrate_attempt_if_needed(attempt_id, answers_payload)
    elif answers_payload:
        _apply_answers_payload(attempt, answers_payload)

    if not attempt:
        return jsonify({"error": "Assessment attempt not found.", "redirect_url": f"/result/{attempt_id}"}), 404

    candidate_id = session.get("candidate_id")
    if candidate_id and attempt.candidate_id != candidate_id:
        return jsonify({"error": "Forbidden: You do not have permission to submit this attempt."}), 403

    if attempt.status == "aborted":
        return jsonify({"error": "Aborted attempts cannot be submitted.", "redirect_url": f"/aborted/{attempt.id}"}), 400

    # Save answers to session so subsequent container cold-starts can rehydrate
    if answers_payload:
        session["candidate_answers"] = answers_payload

    # Finalize and score
    scored_attempt = finalize_and_score_attempt(attempt.id)

    # Cache scored state in session
    session["completed_attempt_id"] = scored_attempt.id
    session["attempt_score"] = scored_attempt.score
    session["attempt_max_score"] = scored_attempt.max_score
    session["attempt_status"] = "completed"

    from app.models.discount import CandidateDiscount
    discount = CandidateDiscount.query.filter_by(attempt_id=scored_attempt.id).first()
    if discount:
        session["discount_pin"] = discount.pin
        session["discount_percent"] = discount.discount_percent
    session.permanent = True

    return jsonify({
        "success": True,
        "message": "Assessment submitted successfully.",
        "redirect_url": url_for("results.result_view", attempt_id=scored_attempt.id)
    })

@assessment_bp.route("/assessment/<attempt_id>/status", methods=["GET"])
def assessment_status(attempt_id):
    """Retrieve remaining time, violation count, and active status for client synchronization."""
    attempt, err = verify_candidate_attempt(attempt_id)
    if err:
        return err

    # Check if timer expired
    expired = check_and_enforce_timer(attempt)
    remaining_sec = get_remaining_seconds(attempt)

    return jsonify({
        "status": attempt.status,
        "remaining_seconds": remaining_sec,
        "violation_count": attempt.violation_count,
        "vision_warning_count": attempt.vision_warning_count or 0,
        "expired": expired
    })

@assessment_bp.route("/assessment/<attempt_id>/retake", methods=["POST"])
def retake_assessment(attempt_id):
    """Initiate a retake with a fresh 15-minute timer and newly randomized questions."""
    attempt, err = verify_candidate_attempt(attempt_id)
    if err:
        return err

    from app.services.discount_service import get_candidate_previous_history
    history = get_candidate_previous_history(attempt.candidate_id)
    bypass_cooldown = request.form.get("bypass_cooldown") == "1" or request.args.get("force") == "1"
    if history["has_previous_attempt"] and history["cooldown_active"] and not bypass_cooldown:
        flash(f"Retake Cooldown: You can retake this assessment in {history['hours_remaining']} hours and {history['minutes_remaining']} minutes.", "warning")
        return redirect(url_for("results.result_view", attempt_id=attempt.id))

    candidate = attempt.candidate
    prior_count = AssessmentAttempt.query.filter_by(candidate_id=candidate.id).count()

    now = utc_now()
    duration_min = current_app.config.get("ASSESSMENT_DURATION_MINUTES", 15)
    deadline = now + timedelta(minutes=duration_min)

    new_attempt = AssessmentAttempt(
        candidate_id=candidate.id,
        attempt_number=prior_count + 1,
        start_time=now,
        deadline=deadline,
        status="in_progress",
        violation_count=0,
        vision_warning_count=0,
        score=0,
        max_score=20,
        unanswered_count=20
    )
    db.session.add(new_attempt)
    db.session.commit()

    generate_questions_for_attempt(new_attempt, questions_per_section=5)

    event = AssessmentEvent(
        attempt_id=new_attempt.id,
        event_type="SESSION_STARTED",
        timestamp=now,
        metadata_json=json.dumps({"retake": True, "prior_attempt_id": attempt.id})
    )
    db.session.add(event)
    db.session.commit()

    return redirect(url_for("assessment.assessment_view", attempt_id=new_attempt.id))
