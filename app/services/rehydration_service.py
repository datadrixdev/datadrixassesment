import uuid
import json
from datetime import datetime, timezone, timedelta
from flask import session, current_app
from app.extensions import db
from app.models.candidate import Candidate
from app.models.assessment import AssessmentAttempt, AttemptQuestion, AssessmentEvent
from app.models.question import Question
from app.models.discount import CandidateDiscount

def utc_now():
    return datetime.now(timezone.utc)

def rehydrate_attempt_if_needed(attempt_id, answers_payload=None):
    """
    Ensures Candidate and AssessmentAttempt exist in the local SQLite database.
    On Vercel serverless environments, cold starts or container lifecycles spawn
    fresh containers with an empty /tmp/assessment.db.
    This safely restores the candidate and exam attempt state from the secure signed session
    and the client's answer payload so the candidate's test is never lost.
    """
    if not attempt_id:
        return None

    candidate_id = session.get("candidate_id")
    if not candidate_id:
        return None

    # 1. Ensure Question seed data exists in this container
    from app.services.question_service import seed_questions_from_file
    try:
        seed_questions_from_file()
    except Exception:
        pass

    # 2. Check if attempt already exists in local DB
    attempt = db.session.get(AssessmentAttempt, attempt_id)
    if attempt:
        if answers_payload and isinstance(answers_payload, list):
            _apply_answers_payload(attempt, answers_payload)
        return attempt

    # 3. Ensure Candidate exists in this container
    candidate = db.session.get(Candidate, candidate_id)
    if not candidate:
        candidate = Candidate(
            id=candidate_id,
            full_name=session.get("candidate_name", "Candidate"),
            email=session.get("candidate_email", "candidate@datadrix.com"),
            mobile_number=session.get("candidate_phone", "")
        )
        db.session.add(candidate)
        try:
            db.session.flush()
        except Exception:
            db.session.rollback()
            candidate = db.session.get(Candidate, candidate_id)

    # 4. Reconstruct Attempt
    now = utc_now()
    duration_min = current_app.config.get("ASSESSMENT_DURATION_MINUTES", 15) if current_app else 15
    attempt_status = session.get("attempt_status", "in_progress")
    score = session.get("attempt_score", 0)
    max_score = session.get("attempt_max_score", 20)

    attempt = AssessmentAttempt(
        id=attempt_id,
        candidate_id=candidate.id if candidate else candidate_id,
        attempt_number=session.get("attempt_number", 1),
        start_time=now - timedelta(minutes=15),
        deadline=now + timedelta(minutes=duration_min),
        end_time=now if attempt_status == "completed" else None,
        status=attempt_status,
        score=score,
        max_score=max_score,
        violation_count=0,
        vision_warning_count=0,
        unanswered_count=max(0, 20 - (len(answers_payload) if answers_payload else 0))
    )
    db.session.add(attempt)
    try:
        db.session.flush()
    except Exception:
        db.session.rollback()
        attempt = db.session.get(AssessmentAttempt, attempt_id)
        if not attempt:
            return None

    # 5. Populate AttemptQuestions
    if not answers_payload:
        answers_payload = session.get("candidate_answers")

    if answers_payload and isinstance(answers_payload, list):
        _apply_answers_payload(attempt, answers_payload)
    elif session.get("assigned_question_codes"):
        # Recreate assigned questions from session codes
        codes = session.get("assigned_question_codes", [])
        for order, code in enumerate(codes, start=1):
            q = Question.query.filter_by(code=code).first()
            if q:
                aq = AttemptQuestion(
                    attempt_id=attempt.id,
                    question_id=q.id,
                    question_order=order,
                    selected_option=None
                )
                db.session.add(aq)
    else:
        from app.services.question_service import generate_questions_for_attempt
        try:
            generate_questions_for_attempt(attempt, questions_per_section=5)
        except Exception:
            pass

    # 6. Recreate CandidateDiscount if present in session
    discount_pin = session.get("discount_pin")
    discount_percent = session.get("discount_percent")
    if discount_pin and discount_percent:
        existing_disc = CandidateDiscount.query.filter_by(pin=discount_pin).first()
        if not existing_disc:
            disc = CandidateDiscount(
                candidate_id=candidate.id if candidate else candidate_id,
                attempt_id=attempt.id,
                pin=discount_pin,
                discount_percent=discount_percent,
                name=candidate.full_name if candidate else session.get("candidate_name", "Candidate"),
                email=candidate.email if candidate else session.get("candidate_email", ""),
                phone=candidate.mobile_number if candidate else session.get("candidate_phone", ""),
                score=score,
                max_score=max_score,
                created_at=now,
                expires_at=now + timedelta(days=3),
                valid_days=3,
                is_used=False
            )
            db.session.add(disc)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return attempt

def _apply_answers_payload(attempt, answers_payload):
    """Update or create AttemptQuestion records from submitted client payload."""
    for item in answers_payload:
        order = item.get("order") or item.get("question_order")
        code = item.get("code")
        selected_option = item.get("selected_option")

        if not order:
            continue

        aq = AttemptQuestion.query.filter_by(attempt_id=attempt.id, question_order=order).first()
        if aq:
            if selected_option is not None:
                aq.selected_option = selected_option
        else:
            q = None
            if code:
                q = Question.query.filter_by(code=code).first()
            if not q:
                all_qs = Question.query.filter_by(is_active=True).all()
                if all_qs and order <= len(all_qs):
                    q = all_qs[order - 1]
            if q:
                new_aq = AttemptQuestion(
                    attempt_id=attempt.id,
                    question_id=q.id,
                    question_order=order,
                    selected_option=selected_option
                )
                db.session.add(new_aq)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
