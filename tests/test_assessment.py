import pytest
from app.models.assessment import AssessmentAttempt, AttemptQuestion
from app.services.question_service import get_candidate_assessment_payload

def test_question_distribution_and_options(app, active_attempt):
    """Verify that an assessment attempt selects exactly 5 questions per section and 20 total."""
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id).order_by(AttemptQuestion.question_order.asc()).all()
    assert len(attempt_questions) == 20

    section_counts = {}
    seen_question_ids = set()

    for aq in attempt_questions:
        q = aq.question
        # Unique questions within attempt
        assert q.id not in seen_question_ids
        seen_question_ids.add(q.id)

        # 4 options present
        assert q.option_a is not None and len(q.option_a.strip()) > 0
        assert q.option_b is not None and len(q.option_b.strip()) > 0
        assert q.option_c is not None and len(q.option_c.strip()) > 0
        assert q.option_d is not None and len(q.option_d.strip()) > 0

        # Valid answer key
        assert q.correct_option in ["A", "B", "C", "D"]

        sec = q.section
        section_counts[sec] = section_counts.get(sec, 0) + 1

    # Exactly 5 per section
    assert section_counts["Reasoning"] == 5
    assert section_counts["General Aptitude"] == 5
    assert section_counts["Logical Reasoning"] == 5
    assert section_counts["English Grammar"] == 5

def test_candidate_payload_conceals_answers(app, active_attempt):
    """Active assessment payload must never expose correct answer or explanation to the client."""
    payload = get_candidate_assessment_payload(active_attempt)
    assert len(payload) == 20

    for q_data in payload:
        assert "order" in q_data
        assert "section" in q_data
        assert "question_text" in q_data
        assert "options" in q_data
        assert len(q_data["options"]) == 4

        # Confidential fields MUST NOT exist
        assert "correct_option" not in q_data
        assert "explanation" not in q_data

def test_save_and_update_answer(client, candidate_session, active_attempt):
    """Saving and modifying answers via the API."""
    # Select Option 'A' for Question 1
    resp = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": "A", "is_marked_for_review": False}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["selected_option"] == "A"
    assert data["is_marked_for_review"] is False

    # Verify database persistence
    aq = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id, question_order=1).first()
    assert aq.selected_option == "A"
    assert aq.is_marked_for_review is False
    assert aq.answered_at is not None

    # Change answer to Option 'C' and mark for review
    resp2 = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": "C", "is_marked_for_review": True}
    )
    assert resp2.status_code == 200
    aq = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id, question_order=1).first()
    assert aq.selected_option == "C"
    assert aq.is_marked_for_review is True

    # Clear selection
    resp3 = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": None}
    )
    assert resp3.status_code == 200
    aq = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id, question_order=1).first()
    assert aq.selected_option is None

def test_save_answer_invalid_options(client, candidate_session, active_attempt):
    """Passing invalid option or question order returns 400 Bad Request."""
    # Invalid option 'Z'
    resp = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": "Z"}
    )
    assert resp.status_code == 400

    # Invalid question order 99
    resp2 = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 99, "selected_option": "A"}
    )
    assert resp2.status_code == 400

def test_start_assessment_cooldown_redirect_and_flash(client, candidate_session, active_attempt):
    """When a candidate is within cooldown, start_assessment flashes a warning and redirects to device-check."""
    from datetime import datetime, timezone, timedelta
    from app.extensions import db

    # Mark active attempt as completed 2 hours ago
    active_attempt.status = "completed"
    active_attempt.score = 15
    active_attempt.end_time = datetime.now(timezone.utc) - timedelta(hours=2)
    db.session.commit()

    resp = client.post("/assessment/start", data={}, follow_redirects=True)
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "Retake Cooldown" in html
    assert "hours" in html

    # With bypass_cooldown=1, it starts the assessment successfully
    resp_bypass = client.post("/assessment/start", data={"bypass_cooldown": "1"}, follow_redirects=False)
    assert resp_bypass.status_code == 302
    assert "/assessment/" in resp_bypass.headers["Location"]

def test_assessment_screen_three_options_and_no_review_buttons(client, candidate_session, active_attempt):
    """Verify assessment screen renders exactly 3 options (A, B, C), live camera feed, and no mark review / clear buttons."""
    resp = client.get(f"/assessment/{active_attempt.id}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    # Only 3 options (A, B, C)
    assert 'data-option="A"' in html
    assert 'data-option="B"' in html
    assert 'data-option="C"' in html
    assert 'data-option="D"' not in html
    assert 'id="optD"' not in html

    # Mark for Review and Clear Selection must be removed
    assert 'id="markReviewBtn"' not in html
    assert 'id="clearSelectionBtn"' not in html

    # Live Proctoring Camera Feed and Canvas must be present
    assert 'id="sidebarProctorVideo"' in html
    assert 'id="sidebarProctorCanvas"' in html
    assert 'id="headMovementModal"' in html

def test_all_questions_solvable_within_three_options(app, active_attempt):
    """All questions in an attempt must have their correct answer within A, B, or C (none requires D)."""
    attempt_questions = AttemptQuestion.query.filter_by(attempt_id=active_attempt.id).all()
    for aq in attempt_questions:
        assert aq.question.correct_option in ["A", "B", "C"]

