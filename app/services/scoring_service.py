import json
from datetime import datetime, timezone
from app.extensions import db
from app.models.assessment import AssessmentAttempt, AttemptQuestion, AssessmentEvent

def utc_now():
    return datetime.now(timezone.utc)

def finalize_and_score_attempt(attempt_id):
    """
    Finalizes an assessment attempt and calculates scores atomically.
    Idempotent: If attempt is already completed, returns existing scored attempt.
    """
    attempt = db.session.get(AssessmentAttempt, attempt_id)
    if not attempt:
        raise ValueError(f"Attempt with ID {attempt_id} not found.")

    # If already completed or aborted, do not recalculate or alter timestamps
    if attempt.status in ["completed", "aborted"]:
        return attempt

    # Gather attempt questions and questions
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=attempt.id).all()

    correct_count = 0
    incorrect_count = 0
    unanswered_count = 0

    section_breakdown = {
        "Reasoning": {"correct": 0, "total": 0},
        "General Aptitude": {"correct": 0, "total": 0},
        "Logical Reasoning": {"correct": 0, "total": 0},
        "English Grammar": {"correct": 0, "total": 0}
    }

    for aq in attempt_questions:
        section = aq.question.section
        if section not in section_breakdown:
            section_breakdown[section] = {"correct": 0, "total": 0}
        section_breakdown[section]["total"] += 1

        if aq.selected_option is None:
            unanswered_count += 1
        elif aq.selected_option == aq.question.correct_option:
            correct_count += 1
            section_breakdown[section]["correct"] += 1
        else:
            incorrect_count += 1

    total_score = correct_count
    max_score = len(attempt_questions) if attempt_questions else 20

    attempt.score = total_score
    attempt.max_score = max_score
    attempt.correct_count = correct_count
    attempt.incorrect_count = incorrect_count
    attempt.unanswered_count = unanswered_count
    attempt.status = "completed"
    attempt.end_time = utc_now()

    # Log event
    event_metadata = {
        "score": total_score,
        "max_score": max_score,
        "correct": correct_count,
        "incorrect": incorrect_count,
        "unanswered": unanswered_count,
        "sections": section_breakdown
    }
    event = AssessmentEvent(
        attempt_id=attempt.id,
        event_type="ASSESSMENT_SUBMITTED",
        timestamp=utc_now(),
        metadata_json=json.dumps(event_metadata)
    )
    db.session.add(event)
    db.session.commit()

    # Automatically generate or sync discount voucher if qualified
    try:
        from app.services.discount_service import create_or_get_discount
        create_or_get_discount(attempt)
    except Exception as disc_err:
        pass

    # Automatically dispatch result report to candidate's registered email
    try:
        from app.services.email_service import send_assessment_result_email
        send_assessment_result_email(attempt)
    except Exception as email_err:
        pass

    return attempt

def get_section_scores(attempt):
    """Calculate section-wise score breakdown for result display."""
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=attempt.id).all()
    sections = {
        "Reasoning": {"name": "Reasoning", "correct": 0, "total": 0, "icon": "bi-cpu"},
        "General Aptitude": {"name": "General Aptitude", "correct": 0, "total": 0, "icon": "bi-calculator"},
        "Logical Reasoning": {"name": "Logical Reasoning", "correct": 0, "total": 0, "icon": "bi-diagram-3"},
        "English Grammar": {"name": "English Grammar", "correct": 0, "total": 0, "icon": "bi-journal-text"}
    }

    for aq in attempt_questions:
        sec = aq.question.section
        if sec not in sections:
            sections[sec] = {"name": sec, "correct": 0, "total": 0, "icon": "bi-card-checklist"}
        sections[sec]["total"] += 1
        if aq.selected_option and aq.selected_option == aq.question.correct_option:
            sections[sec]["correct"] += 1

    results = []
    for sec_data in sections.values():
        total = sec_data["total"] or 1
        pct = round((sec_data["correct"] / total) * 100, 1)
        results.append({
            "name": sec_data["name"],
            "correct": sec_data["correct"],
            "total": sec_data["total"],
            "percentage": pct,
            "icon": sec_data["icon"]
        })
    return results
