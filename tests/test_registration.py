import pytest
from app.models.candidate import Candidate

def test_landing_page_renders(client):
    """GET / renders successfully with 200 OK and expected assessment details."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Online Aptitude Assessment" in html
    assert "Total questions:" in html
    assert "15 minutes" in html
    assert "Candidate Registration" in html

def test_valid_registration(client):
    """Valid form data with selected region creates candidate and redirects to device-check."""
    data = {
        "full_name": "  john doe  ",
        "email": "JOHN.DOE@Example.com",
        "country_code": "+91",
        "mobile_number": "9876543210",
        "consent": "y"
    }
    response = client.post("/register", data=data, follow_redirects=False)
    assert response.status_code == 302
    assert "/device-check" in response.headers["Location"]

    # Verify normalization in database
    candidate = Candidate.query.filter_by(email="john.doe@example.com").first()
    assert candidate is not None
    assert candidate.full_name == "John Doe"
    assert candidate.mobile_number == "+91 9876543210"

def test_registration_missing_country_code(client):
    """Missing region/country code should fail validation."""
    data = {
        "full_name": "John Doe",
        "email": "john.doe@example.com",
        "country_code": "",
        "mobile_number": "9876543210",
        "consent": "y"
    }
    response = client.post("/register", data=data)
    assert response.status_code == 400
    assert "country" in response.data.decode("utf-8").lower() or "region" in response.data.decode("utf-8").lower()

def test_registration_missing_name(client):
    """Missing full name should fail validation with 400 Bad Request."""
    data = {
        "full_name": "",
        "email": "john.doe@example.com",
        "country_code": "+1",
        "mobile_number": "5551234567",
        "consent": "y"
    }
    response = client.post("/register", data=data)
    assert response.status_code == 400
    assert "Full name is required" in response.data.decode("utf-8")

def test_registration_invalid_email(client):
    """Invalid email formats should fail validation."""
    data = {
        "full_name": "John Doe",
        "email": "invalid-email-address",
        "country_code": "+1",
        "mobile_number": "5551234567",
        "consent": "y"
    }
    response = client.post("/register", data=data)
    assert response.status_code == 400

def test_registration_invalid_mobile(client):
    """Mobile number with fewer than 6 digits should fail validation."""
    data = {
        "full_name": "John Doe",
        "email": "john.doe@example.com",
        "country_code": "+1",
        "mobile_number": "123",
        "consent": "y"
    }
    response = client.post("/register", data=data)
    assert response.status_code == 400

def test_registration_missing_consent(client):
    """Failure to check the consent checkbox should reject registration."""
    data = {
        "full_name": "John Doe",
        "email": "john.doe@example.com",
        "country_code": "+1",
        "mobile_number": "5551234567"
        # consent omitted
    }
    response = client.post("/register", data=data)
    assert response.status_code == 400

def test_device_check_requires_session(client):
    """Accessing /device-check without registration session redirects to /."""
    response = client.get("/device-check", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
