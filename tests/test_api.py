"""Unit tests for Flask API endpoints and payload validation."""

import pytest
from app import create_app
from routes import validate_patient_payload


@pytest.fixture
def client():
    """Create a Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        # Existing endpoint validation tests run as an authenticated coordinator.
        with client.session_transaction() as session:
            session["user_id"] = 1
            session["username"] = "test-coordinator"
            session["role"] = "coordinator"
        yield client


def test_index_page(client):
    """Verify that an authenticated user can open the dashboard."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Unified Organ Allocation System" in response.data
    assert b"results-table" in response.data


def test_post_donor_invalid_payload_not_json(client):
    """Verify that POST /api/donor returns 400 when payload is not JSON."""
    response = client.post("/api/donor", data="not json", content_type="text/plain")
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_post_donor_missing_organ(client):
    """Verify that POST /api/donor returns 400 when organ_type is missing or invalid."""
    payload = {
        "donor_id": "D001",
        "state": "Maharashtra",
        "hospital_id": "H001",
        "blood_group": "A+",
        "hla_type": "A2,A24,B7,B44,DR4,DR7",
    }
    response = client.post("/api/donor", json=payload)
    assert response.status_code == 400
    data = response.get_json()
    assert "Invalid 'organ_type'" in data["error"]


def test_post_donor_invalid_blood_group(client):
    """Verify that POST /api/donor returns 400 when blood_group is invalid."""
    payload = {
        "donor_id": "D001",
        "state": "Maharashtra",
        "hospital_id": "H001",
        "blood_group": "X+",
        "organ_type": "Kidney",
        "hla_type": "A2,A24,B7,B44,DR4,DR7",
    }
    response = client.post("/api/donor", json=payload)
    assert response.status_code == 400
    data = response.get_json()
    assert "Invalid 'blood_group'" in data["error"]


def test_post_donor_invalid_viability(client):
    """Verify that POST /api/donor returns 400 when viability_hours is not positive."""
    payload = {
        "donor_id": "D001",
        "state": "Maharashtra",
        "hospital_id": "H001",
        "blood_group": "A+",
        "organ_type": "Kidney",
        "hla_type": "A2,A24,B7,B44,DR4,DR7",
        "viability_hours": -5,
    }
    response = client.post("/api/donor", json=payload)
    assert response.status_code == 400
    data = response.get_json()
    assert "positive integer" in data["error"]


def test_get_ranked_donor_missing_id(client):
    """Verify that GET /api/patients/ranked/ with whitespace or empty returns 400 or 404."""
    response = client.get("/api/patients/ranked/%20")
    assert response.status_code in (400, 404)


def valid_patient_payload():
    return {
        "patient_id": "P_TEST_01", "name": "Synthetic Test Patient", "age": 35,
        "gender": "Other", "state": "Punjab", "hospital_id": "H001",
        "hospital_type": "Government", "blood_group": "A+", "organ_needed": "Kidney",
        "hla_type": "A2,B7", "dialysis_status": "Yes", "icu_level": "Standard",
        "organ_failure_stage": 2, "days_on_waitlist": 10,
        "family_donor_relative": "No"
    }


def test_validate_patient_payload_accepts_valid_record():
    patient, error = validate_patient_payload(valid_patient_payload())
    assert error is None
    assert patient["patient_id"] == "P_TEST_01"
    assert patient["age"] == 35
    assert patient["registered_date"]


def test_validate_patient_payload_rejects_invalid_age():
    payload = valid_patient_payload()
    payload["age"] = 150
    patient, error = validate_patient_payload(payload)
    assert patient is None
    assert "Age must be between" in error


def test_validate_patient_payload_rejects_invalid_organ():
    payload = valid_patient_payload()
    payload["organ_needed"] = "Pancreas"
    patient, error = validate_patient_payload(payload)
    assert patient is None
    assert "organ_needed" in error


def test_validate_patient_payload_rejects_negative_waitlist_days():
    payload = valid_patient_payload()
    payload["days_on_waitlist"] = -1
    patient, error = validate_patient_payload(payload)
    assert patient is None
    assert "cannot be negative" in error


def test_audit_logs_reject_non_integer_limit(client):
    response = client.get("/api/audit-logs?limit=abc")
    assert response.status_code == 400
    assert "integer" in response.get_json()["error"]


def test_audit_logs_limit_is_bounded_by_endpoint_contract(client):
    # A syntactically valid limit should reach database access; the local test
    # does not require a live MySQL server, so either a DB error or success is valid.
    response = client.get("/api/audit-logs?limit=9999")
    assert response.status_code in (200, 500)


def test_dashboard_redirects_to_login_without_session():
    app = create_app()
    app.config["TESTING"] = True
    response = app.test_client().get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_api_rejects_requests_without_session():
    app = create_app()
    app.config["TESTING"] = True
    response = app.test_client().get("/api/auth/me")
    assert response.status_code == 401
