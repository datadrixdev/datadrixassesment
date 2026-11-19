import pytest
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.candidate import Candidate
from app.models.assessment import AssessmentAttempt
from app.models.discount import CandidateDiscount
from app.services.discount_service import (
    calculate_discount,
    generate_10_digit_pin,
    create_or_get_discount,
    get_candidate_previous_history
)

def utc_now():
    return datetime.now(timezone.utc)

def test_discount_score_tiers():
    """Verify exact discount percentages according to candidate score tiers."""
    # Above 7 correct: 20%
    assert calculate_discount(20) == 20
    assert calculate_discount(10) == 20
    assert calculate_discount(8) == 20
    assert calculate_discount(7) == 20

    # 4 to 6: 10%
    assert calculate_discount(6) == 10
    assert calculate_discount(5) == 10
    assert calculate_discount(4) == 10

    # 0 to 3 (no discount): 0%
    assert calculate_discount(3) == 0
    assert calculate_discount(2) == 0
    assert calculate_discount(1) == 0
    assert calculate_discount(0) == 0

def test_10_digit_pin_generation(app):
    """Verify generated key is exactly 10 alphanumeric characters with both capital letters and numbers."""
    with app.app_context():
        pins = set()
        for _ in range(50):
            pin = generate_10_digit_pin(discount_percent=20)
            assert len(pin) == 10
            assert pin.startswith("DX20")
            assert pin.isalnum()
            assert any(c.isupper() for c in pin), f"Key {pin} must contain capital letters"
            assert any(c.isdigit() for c in pin), f"Key {pin} must contain numbers"
            assert pin == pin.upper(), f"Key {pin} must not contain lowercase letters"
            pins.add(pin)

        for _ in range(50):
            pin = generate_10_digit_pin(discount_percent=10)
            assert len(pin) == 10
            assert pin.startswith("DX10")
            assert pin.isalnum()
            assert any(c.isupper() for c in pin), f"Key {pin} must contain capital letters"
            assert any(c.isdigit() for c in pin), f"Key {pin} must contain numbers"
            assert pin == pin.upper(), f"Key {pin} must not contain lowercase letters"
            pins.add(pin)

        assert len(pins) == 100

def test_discount_creation_and_3_day_validity(app, active_attempt):
    """Verify 10-character alphanumeric voucher is created with 3-day validity for qualifying scores."""
    with app.app_context():
        active_attempt.score = 8
        active_attempt.status = "completed"
        active_attempt.end_time = utc_now()
        db.session.commit()

        discount = create_or_get_discount(active_attempt)
        assert discount is not None
        assert discount.discount_percent == 20
        assert len(discount.pin) == 10
        assert discount.pin.startswith("DX20")
        assert discount.pin.isalnum()
        assert any(c.isupper() for c in discount.pin)
        assert any(c.isdigit() for c in discount.pin)
        assert discount.pin == discount.pin.upper()
        assert discount.score == 8
        assert discount.valid_days == 3

        # Expiry is exactly 3 days after creation
        created_time = discount.created_at.replace(tzinfo=timezone.utc) if discount.created_at.tzinfo is None else discount.created_at
        expiry_time = discount.expires_at.replace(tzinfo=timezone.utc) if discount.expires_at.tzinfo is None else discount.expires_at
        diff_days = (expiry_time - created_time).total_seconds() / 86400
        assert abs(diff_days - 3.0) < 0.01
        assert discount.is_active() is True

        # Idempotence: Second call returns the exact same voucher
        discount2 = create_or_get_discount(active_attempt)
        assert discount2.id == discount.id
        assert discount2.pin == discount.pin

def test_no_discount_for_low_scores(app, active_attempt):
    """Scores of 0 to 3 do not receive a discount."""
    with app.app_context():
        active_attempt.score = 3
        active_attempt.status = "completed"
        db.session.commit()

        discount = create_or_get_discount(active_attempt)
        assert discount is None

def test_retake_cooldown_and_previous_history(app, active_attempt):
    """Verify retake cooldown hours and previous score reporting for returning candidates."""
    with app.app_context():
        # Complete attempt 6 hours ago with score 5 (qualifies for 10%)
        active_attempt.score = 5
        active_attempt.status = "completed"
        active_attempt.end_time = utc_now() - timedelta(hours=6)
        db.session.commit()

        create_or_get_discount(active_attempt)

        history = get_candidate_previous_history(active_attempt.candidate_id, cooldown_hours=24)
        assert history["has_previous_attempt"] is True
        assert history["previous_attempt"].score == 5
        assert history["discount"].discount_percent == 10
        assert len(history["discount"].pin) == 10
        assert history["discount"].pin.startswith("DX10")
        
        # 24 hours - 6 hours = ~18 hours remaining
        assert history["cooldown_active"] is True
        assert 17 <= history["hours_remaining"] <= 18

        # After 25 hours, cooldown should be inactive
        history_elapsed = get_candidate_previous_history(active_attempt.candidate_id, cooldown_hours=5)
        assert history_elapsed["cooldown_active"] is False
        assert history_elapsed["hours_remaining"] == 0

def test_candidate_lookup_api(client, app, active_attempt):
    """Verify /api/candidate/lookup endpoint returns previous score, 10-digit pin, and cooldown."""
    active_attempt.score = 19
    active_attempt.status = "completed"
    active_attempt.end_time = utc_now() - timedelta(hours=2)
    db.session.commit()

    with client.session_transaction() as sess:
        sess["candidate_id"] = active_attempt.candidate_id

    create_or_get_discount(active_attempt)

    candidate = active_attempt.candidate
    resp = client.get(f"/api/candidate/lookup?email={candidate.email}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["found"] is True
    assert data["score"] == 19
    assert data["discount_percent"] == 20
    assert len(data["pin"]) == 10
    assert data["cooldown_active"] is True
    assert 21 <= data["hours_remaining"] <= 22
