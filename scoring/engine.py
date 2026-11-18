"""Core scoring engine for organ allocation prototype.

This module provides standalone, pure functions to filter compatible patients,
calculate multi-factor priority scores, and resolve score ties according
to standardized clinical and logistical allocation rules.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping
import pandas as pd

logger = logging.getLogger(__name__)

# Configurable scoring component weights (sum to 1.0)
WEIGHT_URGENCY: float = 0.40
WEIGHT_MATCH: float = 0.30
WEIGHT_WAIT: float = 0.20
WEIGHT_DISTANCE: float = 0.10

# ICU urgency scale mapping (0 - 100)
ICU_SCORE_MAP: dict[str, float] = {
    "Not Admitted": 0.0,
    "Standard": 33.0,
    "ICU": 66.0,
    "Critical": 100.0,
}

# Fixed clinical bonus for kidney patients on active dialysis
KIDNEY_DIALYSIS_BONUS: float = 15.0


def find_compatible_patients(
    donor: Mapping[str, Any] | pd.Series,
    patients_df: pd.DataFrame,
) -> pd.DataFrame:
    """Filter patients by exact blood group match and matching organ needed.

    Args:
        donor: Dictionary or pandas Series representing donor attributes,
            including 'blood_group' and 'organ_type'.
        patients_df: DataFrame of registered candidate patients.

    Returns:
        Filtered DataFrame containing only patients with identical blood group
        and organ_needed matching donor.organ_type.
    """
    if patients_df.empty:
        return patients_df.copy()

    donor_blood = donor["blood_group"]
    donor_organ = donor["organ_type"]

    mask = (patients_df["blood_group"] == donor_blood) & (
        patients_df["organ_needed"] == donor_organ
    )
    return patients_df[mask].copy()


def compute_score(
    patient: Mapping[str, Any] | pd.Series,
    donor: Mapping[str, Any] | pd.Series,
    min_wait: float = 0.0,
    max_wait: float = 0.0,
    weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Compute individual component scores and total weighted allocation score.

    Scoring Formulation:
    1. Medical Urgency (40%):
       - Organ failure stage (1-4) is linearly scaled to [25.0, 100.0] via
         (stage / 4.0) * 100.0.
       - ICU status is mapped to [0.0, 100.0]: Not Admitted=0, Standard=33,
         ICU=66, Critical=100.
       - Base urgency is the equal blend: 0.50 * stage_score + 0.50 * icu_score.
       - Dialysis bonus: If organ_needed is 'Kidney' and dialysis_status is 'Yes',
         a fixed bonus of +15.0 is added.
       - Urgency is bounded within [0.0, 100.0].
    2. Match Quality (30%):
       - HLA allele overlap ratio between patient and donor comma-separated
         alleles: (shared_alleles / max(len(patient_alleles), len(donor_alleles))) * 100.
    3. Waiting Time (20%):
       - Min-max normalized days_on_waitlist relative to the compatible cohort:
         ((days - min_wait) / (max_wait - min_wait)) * 100.
         Defaults to 100.0 if all candidates have the same wait time > 0, else 0.0.
    4. Distance (10%):
       - Proxy score: 100.0 if patient.state == donor.state, else 50.0.

    Args:
        patient: Patient record containing clinical and demographic attributes.
        donor: Donor record containing clinical and geographic attributes.
        min_wait: Minimum waitlist days in current compatible patient cohort.
        max_wait: Maximum waitlist days in current compatible patient cohort.

    Returns:
        Dictionary with urgency_score, match_score, wait_score, distance_score,
        and total_score, rounded to 2 decimal places.
    """
    # 1. Medical Urgency (0 - 100)
    stage = float(patient.get("organ_failure_stage", 1))
    stage_score = (max(1.0, min(4.0, stage)) / 4.0) * 100.0

    icu_status = str(patient.get("icu_level", "Not Admitted")).strip()
    icu_score = ICU_SCORE_MAP.get(icu_status, 0.0)

    base_urgency = (0.50 * stage_score) + (0.50 * icu_score)

    organ = str(patient.get("organ_needed", "")).strip()
    dialysis = str(patient.get("dialysis_status", "No")).strip().lower() == "yes"
    dialysis_bonus = KIDNEY_DIALYSIS_BONUS if (organ == "Kidney" and dialysis) else 0.0

    urgency_score = min(100.0, max(0.0, base_urgency + dialysis_bonus))

    # 2. Match Quality (0 - 100)
    raw_p_hla = str(patient.get("hla_type", ""))
    raw_d_hla = str(donor.get("hla_type", ""))
    patient_alleles = {a.strip() for a in raw_p_hla.split(",") if a.strip()}
    donor_alleles = {a.strip() for a in raw_d_hla.split(",") if a.strip()}

    max_alleles = max(len(patient_alleles), len(donor_alleles))
    if max_alleles > 0:
        shared_count = len(patient_alleles & donor_alleles)
        match_score = (shared_count / float(max_alleles)) * 100.0
    else:
        match_score = 0.0

    # 3. Waiting Time (0 - 100)
    days = float(patient.get("days_on_waitlist", 0))
    if max_wait > min_wait:
        wait_score = ((days - min_wait) / (max_wait - min_wait)) * 100.0
    else:
        wait_score = 100.0 if days > 0 else 0.0
    wait_score = min(100.0, max(0.0, wait_score))

    # 4. Geographic distance (0 - 100), using hospital coordinates where available.
    # Straight-line distance is a proxy, not transport time or clinical viability.
    try:
        lat1, lon1 = float(donor.get("latitude")), float(donor.get("longitude"))
        lat2, lon2 = float(patient.get("latitude")), float(patient.get("longitude"))
        from math import radians, sin, cos, asin, sqrt
        dlat, dlon = radians(lat2-lat1), radians(lon2-lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
        distance_km = 6371.0 * 2 * asin(sqrt(min(1.0, a)))
        # Transparent linear decay: 100 at 0 km, 0 at 1000 km or more.
        distance_score = max(0.0, 100.0 * (1.0 - distance_km / 1000.0))
    except (TypeError, ValueError):
        donor_state = str(donor.get("state", "")).strip()
        patient_state = str(patient.get("state", "")).strip()
        distance_km = None
        distance_score = 100.0 if patient_state == donor_state else 50.0

    # Weighted Total Score
    active_weights = weights or {
        "urgency": WEIGHT_URGENCY, "match": WEIGHT_MATCH,
        "wait": WEIGHT_WAIT, "distance": WEIGHT_DISTANCE,
    }
    total_score = (
        (float(active_weights["urgency"]) * urgency_score)
        + (float(active_weights["match"]) * match_score)
        + (float(active_weights["wait"]) * wait_score)
        + (float(active_weights["distance"]) * distance_score)
    )

    return {
        "urgency_score": round(urgency_score, 2),
        "match_score": round(match_score, 2),
        "wait_score": round(wait_score, 2),
        "distance_score": round(distance_score, 2),
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "total_score": round(total_score, 2),
    }


def _step2_exact_blood_match(p: dict[str, Any]) -> int:
    """Tiebreaker Rule 2: Exact blood type match.

    In this phase, all candidates in the ranked list already have an exact
    blood type match due to the initial compatibility filter (exact match only).
    This function acts as a formal pass-through stub to preserve the sequential
    evaluation specification for future multi-blood compatibility extensions.
    """
    return 1


def apply_tiebreakers(
    ranked_list: list[dict[str, Any]],
    donor: Mapping[str, Any] | pd.Series | None = None,
) -> list[dict[str, Any]]:
    """Apply sequential tiebreaker rules to candidates with identical total scores.

    Rules are evaluated in strict sequence:
    1. Longer days_on_waitlist wins.
    2. Exact blood type match (stub/no-op in this phase since exact match is guaranteed).
    3. Same state as donor wins (closer distance proxy).
    4. Paediatric priority (patient age < 18) wins.
    5. If still tied after all rules: retain original order and set
       'escalate_to_coordinator: True' on the tied entries.

    Args:
        ranked_list: List of candidate patient dictionaries with computed scores.
        donor: Optional donor record for geographic proximity tiebreaking.

    Returns:
        Re-ordered list of candidate dictionaries with 'escalate_to_coordinator' set.
    """
    if not ranked_list:
        return []

    donor_state = str(donor.get("state", "")).strip() if donor else ""

    # Group adjacent or equal total_score entries
    # Use round(..., 2) to match stored decimal precision
    groups: dict[float, list[dict[str, Any]]] = {}
    for item in ranked_list:
        item["escalate_to_coordinator"] = False
        score_key = round(float(item["total_score"]), 2)
        groups.setdefault(score_key, []).append(item)

    final_list: list[dict[str, Any]] = []

    # Process score groups from highest total score to lowest
    for score in sorted(groups.keys(), reverse=True):
        group = groups[score]
        if len(group) == 1:
            final_list.append(group[0])
            continue

        # Sequential tiebreaking across group items
        # Define sorting key tuple reflecting the 4 sequential criteria:
        # 1. days_on_waitlist (higher is better -> negated for reverse order sorting)
        # 2. exact blood match (all equal in this phase -> constant 0)
        # 3. same state (1 if same state, 0 otherwise -> negated)
        # 4. pediatric age < 18 (1 if under 18, 0 otherwise -> negated)

        def tiebreaker_criteria(p: dict[str, Any]) -> tuple[float, int, int, int]:
            wait_days = float(p.get("days_on_waitlist", 0))
            rule2 = _step2_exact_blood_match(p)
            p_state = str(p.get("state", "")).strip()
            same_state = 1 if (donor_state and p_state == donor_state) or (p.get("distance_score", 0.0) == 100.0) else 0
            is_pediatric = 1 if int(p.get("age", 99)) < 18 else 0
            return (wait_days, rule2, same_state, is_pediatric)

        # Sort group by the 4 criteria descending
        # Stable sort preserving original input order where keys match
        sorted_group = sorted(group, key=tiebreaker_criteria, reverse=True)

        # Identify any remaining unresolvable ties across all 4 criteria
        criteria_map: dict[tuple[float, int, int, int], list[dict[str, Any]]] = {}
        for p in sorted_group:
            crit = tiebreaker_criteria(p)
            criteria_map.setdefault(crit, []).append(p)

        for p in sorted_group:
            crit = tiebreaker_criteria(p)
            if len(criteria_map[crit]) > 1:
                p["escalate_to_coordinator"] = True

        final_list.extend(sorted_group)

    return final_list


def generate_ranked_list(
    donor: Mapping[str, Any] | pd.Series,
    patients_df: pd.DataFrame,
    weights: Mapping[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Execute complete allocation pipeline: filter, score, sort, and tiebreak.

    Args:
        donor: Dictionary or Series with donor clinical and geographic data.
        patients_df: DataFrame containing the registered patient pool.

    Returns:
        List of ranked patient dictionaries with explainable score components
        and coordinator escalation flags.
    """
    compatible_df = find_compatible_patients(donor, patients_df)
    if compatible_df.empty:
        return []

    min_wait = float(compatible_df["days_on_waitlist"].min())
    max_wait = float(compatible_df["days_on_waitlist"].max())

    scored_candidates: list[dict[str, Any]] = []
    for _, patient_row in compatible_df.iterrows():
        patient_dict = patient_row.to_dict()
        scores = compute_score(
            patient=patient_dict,
            donor=donor,
            min_wait=min_wait,
            max_wait=max_wait,
            weights=weights,
        )
        patient_dict.update(scores)
        scored_candidates.append(patient_dict)

    # Initial sort descending by total_score
    scored_candidates.sort(key=lambda p: float(p["total_score"]), reverse=True)

    # Apply sequential tiebreakers
    ranked_candidates = apply_tiebreakers(scored_candidates, donor=donor)

    return ranked_candidates
