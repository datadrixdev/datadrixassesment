import pytest
import os
import json
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models.candidate import Candidate
from app.models.question import Question
from app.models.assessment import AssessmentAttempt, AttemptQuestion, AssessmentEvent
from app.models.discount import CandidateDiscount
from app.services.scoring_service import finalize_and_score_attempt, get_section_scores
from app.services.email_service import (
    generate_result_email_html,
    generate_result_email_text,
    send_email_message,
    send_assessment_result_email,
    get_proficiency_meta
)

def utc_now():
    return datetime.now(timezone.utc)

@pytest.fixture
def email_test_data(app):
    """Sets up a candidate with questions and attempt for email testing."""
    with app.app_context():
        candidate = Candidate(
            full_name="Alex Mercer",
            email="alex.mercer@example.com",
            mobile_number="+91 9876543210"
        )
        db.session.add(candidate)
        db.session.commit()

        # Create dummy questions across 4 sections
        questions = []
        sections = ["Reasoning", "General Aptitude", "Logical Reasoning", "English Grammar"]
        for sec in sections:
            for i in range(5):
                q = Question(
                    code=f"EM_{sec[:3].upper()}_{i+1}",
                    section=sec,
                    question_text=f"{sec} Question {i+1}",
                    option_a="Option A",
                    option_b="Option B",
                    option_c="Option C",
                    option_d="Option D",
                    correct_option="A"
                )
                db.session.add(q)
                questions.append(q)
        db.session.commit()

        now = utc_now()
        attempt = AssessmentAttempt(
            candidate_id=candidate.id,
            attempt_number=1,
            start_time=now,
            deadline=now + timedelta(minutes=15),
            status="in_progress",
            score=0,
            max_score=20,
            unanswered_count=20
        )
        db.session.add(attempt)
        db.session.commit()

        # Link questions to attempt and answer 16 of them correctly (80% score)
        for idx, q in enumerate(questions):
            selected = "A" if idx < 16 else "B"  # 16 correct, 4 incorrect
            aq = AttemptQuestion(
                attempt_id=attempt.id,
                question_id=q.id,
                question_order=idx + 1,
                selected_option=selected,
                answered_at=now
            )
            db.session.add(aq)
        db.session.commit()

        candidate_id = candidate.id
        attempt_id = attempt.id

    return {"candidate_id": candidate_id, "attempt_id": attempt_id}

def test_proficiency_meta_categories():
    """Verify proficiency grading and color assignment."""
    assert get_proficiency_meta(90)["grade"] == "Advanced Mastery"
    assert get_proficiency_meta(75)["grade"] == "Proficient"
    assert get_proficiency_meta(55)["grade"] == "Average / Foundational"
    assert get_proficiency_meta(30)["grade"] == "Needs Improvement"

def test_generate_result_email_html(app, email_test_data):
    """Verify HTML email generation contains all expected report fields."""
    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, email_test_data["attempt_id"])
        finalize_and_score_attempt(attempt.id)
        candidate = attempt.candidate
        section_scores = get_section_scores(attempt)
        discount = CandidateDiscount.query.filter_by(attempt_id=attempt.id).first()

        html = generate_result_email_html(candidate, attempt, section_scores, discount)

        # Assert candidate information
        assert "Alex Mercer" in html
        assert "alex.mercer@example.com" in html
        assert "+91 9876543210" in html

        # Assert scores and metrics
        assert f"{attempt.score}" in html
        assert f"{attempt.percentage:.1f}%" in html
        assert "Overall Evaluation Score" in html

        # Assert domain breakdown
        assert "Reasoning" in html
        assert "General Aptitude" in html
        assert "Logical Reasoning" in html
        assert "English Grammar" in html

        # Assert discount voucher if generated
        if discount:
            assert discount.pin in html
            assert f"{discount.discount_percent}%" in html

        # Assert retake policy & online report link
        assert "Retake Cooldown Policy" in html
        assert f"/result/{attempt.id}" in html

        # Assert Datadrix #1 Platform branding & website link
        assert "PREMIER CODING" in html
        assert "https://www.datadrix.com" in html
        assert "DSA &amp; System Design" in html

def test_generate_result_email_text(app, email_test_data):
    """Verify plain text fallback generation."""
    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, email_test_data["attempt_id"])
        finalize_and_score_attempt(attempt.id)
        candidate = attempt.candidate
        section_scores = get_section_scores(attempt)
        discount = CandidateDiscount.query.filter_by(attempt_id=attempt.id).first()

        text = generate_result_email_text(candidate, attempt, section_scores, discount)

        assert "Alex Mercer" in text
        assert "alex.mercer@example.com" in text
        assert f"{attempt.score} / {attempt.max_score}" in text
        assert "Reasoning" in text
        assert "General Aptitude" in text
        assert "PREMIER CODING" in text
        assert "www.datadrix.com" in text

def test_automatic_email_dispatch_on_finalize(app, email_test_data):
    """Verify that finalizing an attempt automatically triggers result email dispatch and logs event."""
    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, email_test_data["attempt_id"])
        finalize_and_score_attempt(attempt.id)

        # Check that AssessmentEvent for report email was created
        email_event = AssessmentEvent.query.filter_by(
            attempt_id=attempt.id,
            event_type="ASSESSMENT_REPORT_EMAILED"
        ).first()

        assert email_event is not None
        meta = json.loads(email_event.metadata_json)
        assert meta["recipient_email"] == "alex.mercer@example.com"
        assert meta["recipient_name"] == "Alex Mercer"
        assert meta["score"] == 16
        assert meta["percentage"] == 80.0

def test_email_local_archive_created(app, email_test_data):
    """Verify that sent email HTML/TXT copies are archived in instance/sent_emails."""
    with app.app_context():
        attempt = db.session.get(AssessmentAttempt, email_test_data["attempt_id"])
        finalize_and_score_attempt(attempt.id)

        base_dir = app.config.get("BASE_DIR", os.getcwd())
        output_dir = os.path.join(base_dir, "instance", "sent_emails")
        html_file = os.path.join(output_dir, f"{attempt.id}_report.html")
        txt_file = os.path.join(output_dir, f"{attempt.id}_report.txt")

        assert os.path.exists(html_file), f"Expected {html_file} to exist."
        assert os.path.exists(txt_file), f"Expected {txt_file} to exist."

        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()
            assert "Alex Mercer" in content
            assert "alex.mercer@example.com" in content
