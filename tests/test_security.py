import pytest
from app.extensions import db
from app.models.candidate import Candidate
from app.models.assessment import AssessmentAttempt
from app.services.scoring_service import finalize_and_score_attempt

def test_cross_candidate_access_forbidden(client, app, active_attempt):
    """Candidate B cannot view or modify Candidate A's assessment or results."""
    # Create Candidate B
    candidate_b = Candidate(
        full_name="Bob Smith",
        email="bob@example.com",
        mobile_number="+15559998888"
    )
    db.session.add(candidate_b)
    db.session.commit()

    # Log in as Candidate B
    with client.session_transaction() as sess:
        sess["candidate_id"] = candidate_b.id
        sess["candidate_name"] = candidate_b.full_name
        sess["candidate_email"] = candidate_b.email

    # Attempt to view Candidate A's active assessment
    resp = client.get(f"/assessment/{active_attempt.id}")
    assert resp.status_code == 403

    # Attempt to submit an answer for Candidate A's assessment
    resp2 = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": "A"}
    )
    assert resp2.status_code == 403

    # Attempt to view Candidate A's results after completion
    finalize_and_score_attempt(active_attempt.id)
    resp3 = client.get(f"/result/{active_attempt.id}")
    assert resp3.status_code == 403

def test_unauthenticated_access_blocked(client, active_attempt):
    """Unauthenticated client cannot access assessment or API."""
    # Clear session
    with client.session_transaction() as sess:
        sess.clear()

    resp = client.get(f"/assessment/{active_attempt.id}")
    assert resp.status_code == 401

    resp2 = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": "A"}
    )
    assert resp2.status_code == 401

def test_active_html_does_not_leak_answers(client, candidate_session, active_attempt):
    """Active assessment HTML template must not contain answer explanations or keys."""
    resp = client.get(f"/assessment/{active_attempt.id}")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    # Ensure correct_option and explanation are not exposed in the inline JS or HTML
    assert "correct_option" not in html
    assert "explanation" not in html

def test_cannot_modify_completed_attempt(client, candidate_session, active_attempt):
    """Answers cannot be added or modified once the attempt has been finalized."""
    finalize_and_score_attempt(active_attempt.id)

    resp = client.post(
        f"/api/assessment/{active_attempt.id}/answer",
        json={"question_order": 1, "selected_option": "D"}
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "completed" in data.get("error", "").lower()
