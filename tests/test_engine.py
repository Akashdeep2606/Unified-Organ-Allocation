"""Unit and integration tests for organ allocation scoring engine."""

import math
import pandas as pd
import pytest

from scoring.engine import (
    WEIGHT_DISTANCE,
    WEIGHT_MATCH,
    WEIGHT_URGENCY,
    WEIGHT_WAIT,
    apply_tiebreakers,
    compute_score,
    find_compatible_patients,
    generate_ranked_list,
)


@pytest.fixture
def sample_donor() -> dict:
    """Fixture providing a standard sample donor."""
    return {
        "donor_id": "D001",
        "state": "Maharashtra",
        "hospital_id": "H001",
        "blood_group": "A+",
        "organ_type": "Kidney",
        "hla_type": "A2,A24,B7,B44,DR4,DR7",
        "logged_datetime": "2026-09-01 10:00:00",
        "viability_hours": 24,
    }


@pytest.fixture
def sample_patients_df() -> pd.DataFrame:
    """Fixture providing a diverse patient cohort."""
    return pd.DataFrame([
        {
            "patient_id": "P001",
            "name": "Patient Compatible A+",
            "age": 45,
            "gender": "Male",
            "state": "Maharashtra",
            "hospital_id": "H001",
            "hospital_type": "Government",
            "blood_group": "A+",
            "organ_needed": "Kidney",
            "hla_type": "A2,A24,B7,B44,DR4,DR7",
            "dialysis_status": "Yes",
            "icu_level": "ICU",
            "organ_failure_stage": 4,
            "days_on_waitlist": 300,
            "family_donor_relative": "No",
            "registered_date": "2025-11-01",
        },
        {
            "patient_id": "P002",
            "name": "Patient Wrong Blood",
            "age": 30,
            "gender": "Female",
            "state": "Maharashtra",
            "hospital_id": "H001",
            "hospital_type": "Government",
            "blood_group": "B+",
            "organ_needed": "Kidney",
            "hla_type": "A2,A24,B7,B44,DR4,DR7",
            "dialysis_status": "No",
            "icu_level": "Standard",
            "organ_failure_stage": 3,
            "days_on_waitlist": 200,
            "family_donor_relative": "No",
            "registered_date": "2026-02-01",
        },
        {
            "patient_id": "P003",
            "name": "Patient Wrong Organ",
            "age": 50,
            "gender": "Male",
            "state": "Punjab",
            "hospital_id": "H002",
            "hospital_type": "Private",
            "blood_group": "A+",
            "organ_needed": "Liver",
            "hla_type": "A2,A24,B7,B44,DR4,DR7",
            "dialysis_status": "No",
            "icu_level": "Critical",
            "organ_failure_stage": 4,
            "days_on_waitlist": 400,
            "family_donor_relative": "No",
            "registered_date": "2025-08-01",
        },
    ])


def test_find_compatible_patients_matching(sample_donor: dict, sample_patients_df: pd.DataFrame) -> None:
    """Verify filter returns only candidates matching both blood group and organ needed."""
    compatible = find_compatible_patients(sample_donor, sample_patients_df)
    assert len(compatible) == 1
    assert compatible.iloc[0]["patient_id"] == "P001"
    assert compatible.iloc[0]["blood_group"] == "A+"
    assert compatible.iloc[0]["organ_needed"] == "Kidney"


def test_find_compatible_patients_no_match(sample_donor: dict) -> None:
    """Verify filter returns empty DataFrame when no patient matches."""
    empty_df = pd.DataFrame([
        {
            "patient_id": "P999",
            "blood_group": "O-",
            "organ_needed": "Heart",
        }
    ])
    compatible = find_compatible_patients(sample_donor, empty_df)
    assert compatible.empty


def test_compute_score_components_sum(sample_donor: dict) -> None:
    """Verify all four score components sum correctly to total_score using configured weights."""
    patient = {
        "patient_id": "P100",
        "organ_needed": "Kidney",
        "organ_failure_stage": 3,
        "icu_level": "Standard",
        "dialysis_status": "Yes",
        "hla_type": "A2,A24,B7,DR4",  # 4 out of 6 match with sample_donor
        "days_on_waitlist": 150,
        "state": "Maharashtra",
    }

    scores = compute_score(patient, sample_donor, min_wait=100.0, max_wait=200.0)

    # Verify score presence
    assert "urgency_score" in scores
    assert "match_score" in scores
    assert "wait_score" in scores
    assert "distance_score" in scores
    assert "total_score" in scores

    # Calculate expected sum
    expected_total = (
        (WEIGHT_URGENCY * scores["urgency_score"])
        + (WEIGHT_MATCH * scores["match_score"])
        + (WEIGHT_WAIT * scores["wait_score"])
        + (WEIGHT_DISTANCE * scores["distance_score"])
    )

    assert math.isclose(scores["total_score"], round(expected_total, 2), abs_tol=0.01)


def test_apply_tiebreakers_waitlist(sample_donor: dict) -> None:
    """Verify synthetic tie is resolved in favor of longer days_on_waitlist."""
    p1 = {
        "patient_id": "PTIE1",
        "name": "Shorter Wait",
        "total_score": 75.00,
        "days_on_waitlist": 120,
        "state": "Maharashtra",
        "age": 35,
        "distance_score": 100.0,
    }
    p2 = {
        "patient_id": "PTIE2",
        "name": "Longer Wait",
        "total_score": 75.00,
        "days_on_waitlist": 450,
        "state": "Maharashtra",
        "age": 40,
        "distance_score": 100.0,
    }

    ranked = apply_tiebreakers([p1, p2], donor=sample_donor)

    assert len(ranked) == 2
    assert ranked[0]["patient_id"] == "PTIE2"
    assert ranked[1]["patient_id"] == "PTIE1"
    assert not ranked[0]["escalate_to_coordinator"]


def test_apply_tiebreakers_pediatric_fallback(sample_donor: dict) -> None:
    """Verify tie falls through to paediatric priority (age < 18) when waitlist and state are tied."""
    p_adult = {
        "patient_id": "P_ADULT",
        "name": "Adult Candidate",
        "total_score": 80.00,
        "days_on_waitlist": 250,
        "state": "Maharashtra",
        "age": 32,
        "distance_score": 100.0,
    }
    p_child = {
        "patient_id": "P_CHILD",
        "name": "Pediatric Candidate",
        "total_score": 80.00,
        "days_on_waitlist": 250,
        "state": "Maharashtra",
        "age": 12,
        "distance_score": 100.0,
    }

    ranked = apply_tiebreakers([p_adult, p_child], donor=sample_donor)

    assert len(ranked) == 2
    assert ranked[0]["patient_id"] == "P_CHILD"
    assert ranked[1]["patient_id"] == "P_ADULT"
    assert not ranked[0]["escalate_to_coordinator"]


def test_apply_tiebreakers_escalate_to_coordinator(sample_donor: dict) -> None:
    """Verify escalate_to_coordinator is set to True when all tiebreaker rules fail to break a tie."""
    p_identical_1 = {
        "patient_id": "P_TWIN1",
        "name": "Twin 1",
        "total_score": 85.00,
        "days_on_waitlist": 300,
        "state": "Maharashtra",
        "age": 28,
        "distance_score": 100.0,
    }
    p_identical_2 = {
        "patient_id": "P_TWIN2",
        "name": "Twin 2",
        "total_score": 85.00,
        "days_on_waitlist": 300,
        "state": "Maharashtra",
        "age": 28,
        "distance_score": 100.0,
    }

    ranked = apply_tiebreakers([p_identical_1, p_identical_2], donor=sample_donor)

    assert len(ranked) == 2
    assert ranked[0]["escalate_to_coordinator"] is True
    assert ranked[1]["escalate_to_coordinator"] is True


def test_generate_ranked_list_integration(sample_donor: dict) -> None:
    """Integration test: Verify complete pipeline on a small 5-patient cohort produces properly sorted output."""
    patients = pd.DataFrame([
        {
            "patient_id": "P_HIGH",
            "name": "High Urgency & Overlap",
            "age": 35,
            "gender": "Male",
            "state": "Maharashtra",
            "hospital_id": "H001",
            "hospital_type": "Government",
            "blood_group": "A+",
            "organ_needed": "Kidney",
            "hla_type": "A2,A24,B7,B44,DR4,DR7",
            "dialysis_status": "Yes",
            "icu_level": "Critical",
            "organ_failure_stage": 4,
            "days_on_waitlist": 500,
            "family_donor_relative": "No",
            "registered_date": "2025-01-01",
        },
        {
            "patient_id": "P_MED",
            "name": "Moderate Urgency",
            "age": 42,
            "gender": "Female",
            "state": "Maharashtra",
            "hospital_id": "H001",
            "hospital_type": "Private",
            "blood_group": "A+",
            "organ_needed": "Kidney",
            "hla_type": "A2,A24,B7",
            "dialysis_status": "No",
            "icu_level": "Standard",
            "organ_failure_stage": 2,
            "days_on_waitlist": 250,
            "family_donor_relative": "No",
            "registered_date": "2025-08-01",
        },
        {
            "patient_id": "P_LOW",
            "name": "Low Urgency Out of State",
            "age": 55,
            "gender": "Male",
            "state": "Punjab",
            "hospital_id": "H003",
            "hospital_type": "Government",
            "blood_group": "A+",
            "organ_needed": "Kidney",
            "hla_type": "A1,B8",
            "dialysis_status": "No",
            "icu_level": "Not Admitted",
            "organ_failure_stage": 1,
            "days_on_waitlist": 50,
            "family_donor_relative": "No",
            "registered_date": "2026-07-01",
        },
        {
            "patient_id": "P_INCOMPAT_BLOOD",
            "name": "B Blood Group",
            "age": 30,
            "gender": "Female",
            "state": "Maharashtra",
            "hospital_id": "H001",
            "hospital_type": "Government",
            "blood_group": "B+",
            "organ_needed": "Kidney",
            "hla_type": "A2,A24,B7,B44,DR4,DR7",
            "dialysis_status": "Yes",
            "icu_level": "Critical",
            "organ_failure_stage": 4,
            "days_on_waitlist": 600,
            "family_donor_relative": "No",
            "registered_date": "2024-12-01",
        },
        {
            "patient_id": "P_INCOMPAT_ORGAN",
            "name": "Heart Needed",
            "age": 28,
            "gender": "Male",
            "state": "Maharashtra",
            "hospital_id": "H001",
            "hospital_type": "Government",
            "blood_group": "A+",
            "organ_needed": "Heart",
            "hla_type": "A2,A24,B7,B44,DR4,DR7",
            "dialysis_status": "No",
            "icu_level": "Critical",
            "organ_failure_stage": 4,
            "days_on_waitlist": 400,
            "family_donor_relative": "No",
            "registered_date": "2025-05-01",
        },
    ])

    results = generate_ranked_list(sample_donor, patients)

    # Incompatible patients must be excluded
    result_ids = [p["patient_id"] for p in results]
    assert "P_INCOMPAT_BLOOD" not in result_ids
    assert "P_INCOMPAT_ORGAN" not in result_ids
    assert len(results) == 3

    # Ranking must be strictly descending by total_score
    scores = [p["total_score"] for p in results]
    assert scores == sorted(scores, reverse=True)

    # P_HIGH must rank 1st
    assert results[0]["patient_id"] == "P_HIGH"
    assert results[1]["patient_id"] == "P_MED"
    assert results[2]["patient_id"] == "P_LOW"
