import pytest
from app.extensions import db
from app.models.assessment import AttemptQuestion
from app.services.scoring_service import finalize_and_score_attempt, get_section_scores
from app.services.question_service import get_attempt_review_data

def test_perfect_scoring(app, active_attempt):
    """An attempt with all 20 questions answered correctly scores 20/20 (100%)."""
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id).all()
    for aq in attempt_questions:
        aq.selected_option = aq.question.correct_option
    db.session.commit()

    scored = finalize_and_score_attempt(active_attempt.id)
    assert scored.score == 20
    assert scored.percentage == 100.0
    assert scored.correct_count == 20
    assert scored.incorrect_count == 0
    assert scored.unanswered_count == 0
    assert scored.status == "completed"

def test_mixed_scoring_no_negative_marking(app, active_attempt):
    """Verify accurate counts for correct, incorrect, and unanswered without negative penalty."""
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id).order_by(AttemptQuestion.question_order.asc()).all()

    # Answer first 12 correctly
    for aq in attempt_questions[:12]:
        aq.selected_option = aq.question.correct_option

    # Answer next 5 incorrectly
    for aq in attempt_questions[12:17]:
        wrong_opt = "A" if aq.question.correct_option != "A" else "B"
        aq.selected_option = wrong_opt

    # Leave last 3 unanswered
    for aq in attempt_questions[17:]:
        aq.selected_option = None

    db.session.commit()

    scored = finalize_and_score_attempt(active_attempt.id)
    assert scored.score == 12
    assert scored.percentage == 60.0
    assert scored.correct_count == 12
    assert scored.incorrect_count == 5
    assert scored.unanswered_count == 3
    assert scored.status == "completed"

def test_section_wise_scoring(app, active_attempt):
    """Calculate section-wise scores across the 4 sections."""
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id).all()
    # Mark all Reasoning questions (1-5) as correct
    for aq in attempt_questions:
        if aq.question.section == "Reasoning":
            aq.selected_option = aq.question.correct_option
        else:
            aq.selected_option = None
    db.session.commit()

    finalize_and_score_attempt(active_attempt.id)
    section_breakdown = get_section_scores(active_attempt)

    sec_map = {s["name"]: s for s in section_breakdown}
    assert sec_map["Reasoning"]["correct"] == 5
    assert sec_map["Reasoning"]["percentage"] == 100.0
    assert sec_map["General Aptitude"]["correct"] == 0
    assert sec_map["Logical Reasoning"]["correct"] == 0
    assert sec_map["English Grammar"]["correct"] == 0

def test_idempotent_submission(app, active_attempt):
    """Multiple submissions or score invocations do not duplicate scores or alter end_time."""
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id).all()
    for aq in attempt_questions[:10]:
        aq.selected_option = aq.question.correct_option
    db.session.commit()

    scored1 = finalize_and_score_attempt(active_attempt.id)
    first_end_time = scored1.end_time
    first_score = scored1.score

    # Second invocation
    scored2 = finalize_and_score_attempt(active_attempt.id)
    assert scored2.score == first_score
    assert scored2.end_time == first_end_time
    assert scored2.status == "completed"

def test_result_review_data(app, active_attempt):
    """Internal service review helper maintains consistency."""
    finalize_and_score_attempt(active_attempt.id)
    review_items = get_attempt_review_data(active_attempt)

    assert len(review_items) == 20
    for item in review_items:
        assert item["correct_option"] in ["A", "B", "C", "D"]
        assert item["explanation"] is not None
        assert item["status"] in ["correct", "incorrect", "unanswered"]

def test_result_page_shows_only_reports_not_questions(client, candidate_session, active_attempt):
    """Per user specification: Result page displays reports only, without revealing questions or answer keys."""
    finalize_and_score_attempt(active_attempt.id)
    resp = client.get(f"/result/{active_attempt.id}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Candidate Assessment Report" in html
    assert "Cognitive &amp; Skill Competency Matrix" not in html
    assert "Domain-wise Performance Analysis" not in html
    # Ensure individual questions and answer keys are NOT rendered in the final report
    assert "Detailed Question Review" not in html
    assert "Question 1 of 20" not in html

