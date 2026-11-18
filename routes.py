"""Flask API routes for donor registration and patient ranking."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from flask import Blueprint, jsonify, request, Response, session
import pandas as pd
from werkzeug.security import check_password_hash, generate_password_hash
from mysql.connector import Error as MySQLError

from db.connection import get_cursor
from scoring.engine import generate_ranked_list, WEIGHT_URGENCY, WEIGHT_MATCH, WEIGHT_WAIT, WEIGHT_DISTANCE

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")

VALID_BLOOD_GROUPS: set[str] = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"}
VALID_ORGANS: set[str] = {"Kidney", "Liver", "Heart", "Lung"}
VALID_GENDERS: set[str] = {"Male", "Female", "Other"}
VALID_HOSPITAL_TYPES: set[str] = {"Government", "Private"}
VALID_YES_NO: set[str] = {"Yes", "No"}
VALID_ICU_LEVELS: set[str] = {"Not Admitted", "Standard", "ICU", "Critical"}


@api_bp.before_request
def require_login():
    """Require an authenticated session for every API endpoint except login."""
    if request.endpoint == "api.login":
        return None
    if not session.get("user_id"):
        return jsonify({"error": "Authentication required. Please log in."}), 401
    return None


def user_has_role(*roles: str) -> bool:
    return session.get("role") in roles


@api_bp.route("/auth/login", methods=["POST"])
def login() -> tuple[Response, int]:
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    requested_role = str(data.get("role", "")).strip().lower()
    if not username or not password or requested_role not in {"admin", "coordinator", "hospital"}:
        return jsonify({"error": "Select a role and enter both username and password."}), 400
    try:
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT user_id, username, password_hash, role, hospital_id, is_active FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
    except MySQLError:
        logger.exception("Login lookup failed")
        return jsonify({"error": "Login database is not ready. Run db/migration_users.sql and create an admin user."}), 503
    if (not user or not user.get("is_active")
            or user.get("role") != requested_role
            or not check_password_hash(user["password_hash"], password)):
        return jsonify({"error": "Invalid credentials or selected role does not match this account."}), 401
    session.clear()
    session["user_id"] = int(user["user_id"])
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["hospital_id"] = user.get("hospital_id")
    return jsonify({"message": "Login successful.", "username": user["username"], "role": user["role"], "hospital_id": user.get("hospital_id")}), 200


@api_bp.route("/users", methods=["POST", "GET"])
def manage_users() -> tuple[Response, int]:
    """Admin-only user provisioning; passwords are stored as Werkzeug hashes."""
    if not user_has_role("admin"):
        return jsonify({"error": "Only administrators can manage user accounts."}), 403
    if request.method == "GET":
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT user_id, username, role, hospital_id, is_active, created_at FROM users ORDER BY created_at DESC")
            rows = cursor.fetchall() or []
        for row in rows:
            if isinstance(row.get("created_at"), datetime):
                row["created_at"] = row["created_at"].isoformat(sep=" ")
        return jsonify(rows), 200
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    role = str(data.get("role", "")).strip().lower()
    hospital_id = str(data.get("hospital_id", "")).strip() or None
    if len(username) < 3 or len(username) > 80:
        return jsonify({"error": "Username must contain 3 to 80 characters."}), 400
    if len(password) < 10:
        return jsonify({"error": "Password must contain at least 10 characters."}), 400
    if role not in {"coordinator", "hospital"}:
        return jsonify({"error": "Role must be coordinator or hospital. Create admins through the secured setup script."}), 400
    if role == "hospital" and not hospital_id:
        return jsonify({"error": "Hospital accounts must be linked to a hospital_id."}), 400
    try:
        with get_cursor(commit=True) as cursor:
            if hospital_id:
                cursor.execute("SELECT hospital_id FROM hospitals WHERE hospital_id=%s", (hospital_id,))
                if not cursor.fetchone():
                    return jsonify({"error": "Hospital ID does not exist."}), 400
            cursor.execute("INSERT INTO users (username, password_hash, role, hospital_id, is_active) VALUES (%s, %s, %s, %s, TRUE)",
                           (username, generate_password_hash(password), role, hospital_id))
        write_audit_event("USER_CREATED", username, {"role": role, "created_by": session.get("username")})
        return jsonify({"message": f"{role.title()} account created.", "username": username, "role": role}), 201
    except MySQLError as exc:
        if getattr(exc, "errno", None) == 1062:
            return jsonify({"error": "That username already exists."}), 409
        logger.exception("User creation failed")
        return jsonify({"error": "Could not create user account."}), 500


@api_bp.route("/auth/logout", methods=["POST"])
def logout() -> tuple[Response, int]:
    session.clear()
    return jsonify({"message": "Logged out."}), 200


@api_bp.route("/auth/me", methods=["GET"])
def current_user() -> tuple[Response, int]:
    return jsonify({"username": session.get("username"), "role": session.get("role"), "hospital_id": session.get("hospital_id")}), 200


def write_audit_event(event_type: str, entity_id: str, details: dict[str, Any]) -> None:
    """Persist a minimal audit event. Apply db/migration_audit_log.sql first."""
    import json
    sql = """INSERT INTO audit_logs (event_type, entity_id, details_json, created_at)
             VALUES (%s, %s, %s, NOW())"""
    with get_cursor(commit=True) as cursor:
        cursor.execute(sql, (event_type, entity_id, json.dumps(details, default=str)))


DEFAULT_WEIGHTS = {"urgency": WEIGHT_URGENCY, "match": WEIGHT_MATCH, "wait": WEIGHT_WAIT, "distance": WEIGHT_DISTANCE}


def get_scoring_weights() -> dict[str, float]:
    """Read active scoring weights; fall back to defaults before migration."""
    try:
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT urgency_weight, match_weight, wait_weight, distance_weight FROM scoring_policy WHERE policy_id = 1")
            row = cursor.fetchone()
        if row:
            return {"urgency": float(row["urgency_weight"]), "match": float(row["match_weight"]),
                    "wait": float(row["wait_weight"]), "distance": float(row["distance_weight"])}
    except MySQLError:
        logger.warning("Scoring policy table unavailable; using default weights. Apply migration_scoring_policy.sql.")
    return DEFAULT_WEIGHTS.copy()


@api_bp.route("/scoring-weights", methods=["GET", "PUT"])
def scoring_weights() -> tuple[Response, int]:
    """Read or update simulation weights for authenticated users."""
    if request.method == "GET":
        return jsonify(get_scoring_weights()), 200
    if not user_has_role("admin", "coordinator"):
        return jsonify({"error": "Only administrators or coordinators can change scoring policy."}), 403
    data = request.get_json(silent=True)
    keys = ("urgency", "match", "wait", "distance")
    if not isinstance(data, dict) or any(k not in data for k in keys):
        return jsonify({"error": "Provide urgency, match, wait and distance weights."}), 400
    try:
        weights = {k: float(data[k]) for k in keys}
    except (TypeError, ValueError):
        return jsonify({"error": "All weights must be numeric percentages."}), 400
    if any(v < 0 or v > 100 for v in weights.values()) or abs(sum(weights.values()) - 100.0) > 0.001:
        return jsonify({"error": "Weights must each be between 0 and 100 and total exactly 100%."}), 400
    try:
        with get_cursor(commit=True) as cursor:
            cursor.execute("""INSERT INTO scoring_policy (policy_id, urgency_weight, match_weight, wait_weight, distance_weight, updated_at)
                VALUES (1, %s, %s, %s, %s, NOW()) ON DUPLICATE KEY UPDATE
                urgency_weight=VALUES(urgency_weight), match_weight=VALUES(match_weight),
                wait_weight=VALUES(wait_weight), distance_weight=VALUES(distance_weight), updated_at=NOW()""",
                tuple(weights[k] / 100.0 for k in keys))
        write_audit_event("SCORING_POLICY_UPDATED", "POLICY_1", weights)
        return jsonify({"message": "Scoring weights saved. They apply to future rankings.", **weights}), 200
    except MySQLError as exc:
        logger.error("Could not save scoring policy: %s", exc)
        return jsonify({"error": "Could not save weights. Run the scoring-policy SQL migration first."}), 500


def validate_patient_payload(data: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a patient record against the existing patients table schema."""
    if not isinstance(data, dict):
        return None, "Request body must be a valid JSON object."
    required = ["patient_id", "name", "age", "gender", "state", "hospital_id",
                "hospital_type", "blood_group", "organ_needed", "hla_type",
                "dialysis_status", "icu_level", "organ_failure_stage",
                "days_on_waitlist", "family_donor_relative"]
    missing = [key for key in required if str(data.get(key, "")).strip() == ""]
    if missing:
        return None, "Missing required fields: " + ", ".join(missing)
    try:
        age = int(data["age"])
        stage = int(data["organ_failure_stage"])
        days = int(data["days_on_waitlist"])
    except (TypeError, ValueError):
        return None, "Age, organ_failure_stage and days_on_waitlist must be integers."
    if not 0 <= age <= 120:
        return None, "Age must be between 0 and 120."
    if not 1 <= stage <= 4:
        return None, "organ_failure_stage must be between 1 and 4."
    if days < 0:
        return None, "days_on_waitlist cannot be negative."
    patient = {key: str(data[key]).strip() for key in required if key not in {"age", "organ_failure_stage", "days_on_waitlist"}}
    patient.update(age=age, organ_failure_stage=stage, days_on_waitlist=days)
    patient["registered_date"] = str(data.get("registered_date") or datetime.now().strftime("%Y-%m-%d"))
    if patient["gender"] not in VALID_GENDERS:
        return None, f"gender must be one of {sorted(VALID_GENDERS)}."
    if patient["hospital_type"] not in VALID_HOSPITAL_TYPES:
        return None, f"hospital_type must be one of {sorted(VALID_HOSPITAL_TYPES)}."
    if patient["blood_group"] not in VALID_BLOOD_GROUPS:
        return None, f"Invalid blood_group. Must be one of {sorted(VALID_BLOOD_GROUPS)}."
    if patient["organ_needed"] not in VALID_ORGANS:
        return None, f"organ_needed must be one of {sorted(VALID_ORGANS)}."
    if patient["dialysis_status"] not in VALID_YES_NO or patient["family_donor_relative"] not in VALID_YES_NO:
        return None, "dialysis_status and family_donor_relative must be Yes or No."
    if patient["icu_level"] not in VALID_ICU_LEVELS:
        return None, f"icu_level must be one of {sorted(VALID_ICU_LEVELS)}."
    try:
        datetime.strptime(patient["registered_date"], "%Y-%m-%d")
    except ValueError:
        return None, "registered_date must use YYYY-MM-DD format."
    return patient, None


def validate_donor_payload(data: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate incoming donor JSON payload against business and schema constraints.

    Args:
        data: Parsed JSON payload from the request.

    Returns:
        A tuple of (validated_dict, error_message). If invalid, validated_dict is None.
    """
    if not isinstance(data, dict):
        return None, "Request body must be a valid JSON object."

    donor_id = str(data.get("donor_id", "")).strip()
    if not donor_id:
        # Generate default unique donor ID if omitted
        donor_id = f"D_{int(datetime.utcnow().timestamp())}"

    state = str(data.get("state", "")).strip()
    if not state:
        return None, "Missing required field: 'state'."

    hospital_id = str(data.get("hospital_id", "")).strip()
    if not hospital_id:
        return None, "Missing required field: 'hospital_id'."

    blood_group = str(data.get("blood_group", "")).strip()
    if blood_group not in VALID_BLOOD_GROUPS:
        return None, (
            f"Invalid 'blood_group': '{blood_group}'. "
            f"Must be one of {sorted(VALID_BLOOD_GROUPS)}."
        )

    organ_type = str(data.get("organ_type", "")).strip()
    if organ_type not in VALID_ORGANS:
        return None, (
            f"Invalid 'organ_type': '{organ_type}'. "
            f"Must be one of {sorted(VALID_ORGANS)}."
        )

    hla_type = str(data.get("hla_type", "")).strip()
    if not hla_type:
        return None, "Missing required field: 'hla_type'."

    logged_datetime = str(data.get("logged_datetime", "")).strip()
    if not logged_datetime:
        logged_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    else:
        # Validate format
        try:
            # Accepts common formats (e.g. 2026-09-16 12:00:00 or ISO)
            cleaned_dt = logged_datetime.replace("T", " ")
            parsed_dt = datetime.strptime(cleaned_dt[:19], "%Y-%m-%d %H:%M:%S")
            logged_datetime = parsed_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None, (
                f"Invalid 'logged_datetime' format: '{logged_datetime}'. "
                "Expected 'YYYY-MM-DD HH:MM:SS'."
            )

    try:
        viability_hours = int(data.get("viability_hours", 24))
        if viability_hours <= 0:
            return None, "'viability_hours' must be a positive integer."
    except (TypeError, ValueError):
        return None, "'viability_hours' must be a valid integer."

    validated: dict[str, Any] = {
        "donor_id": donor_id,
        "state": state,
        "hospital_id": hospital_id,
        "blood_group": blood_group,
        "organ_type": organ_type,
        "hla_type": hla_type,
        "logged_datetime": logged_datetime,
        "viability_hours": viability_hours,
    }
    return validated, None


def fetch_active_patients_df() -> pd.DataFrame:
    """Fetch all registered candidate patients from the database.

    Returns:
        pandas DataFrame containing all registered patient rows.

    Raises:
        MySQLError: If database query encounters an error.
    """
    query = """
        SELECT
            patient_id, name, age, gender, state, hospital_id, hospital_type,
            blood_group, organ_needed, hla_type, dialysis_status, icu_level,
            organ_failure_stage, days_on_waitlist, family_donor_relative, registered_date
        FROM patients;
    """
    with get_cursor(dictionary=True, commit=False) as cursor:
        query = query.replace("FROM patients;", "FROM patients p LEFT JOIN hospitals h ON h.hospital_id=p.hospital_id;")
        query = query.replace("patient_id, name, age, gender, state, hospital_id, hospital_type,", "p.patient_id, name, age, gender, p.state, p.hospital_id, p.hospital_type, h.latitude, h.longitude,")
        cursor.execute(query)
        rows = cursor.fetchall()
        return pd.DataFrame(rows)


def save_donor_record(donor: dict[str, Any]) -> None:
    """Insert or update a donor record in the MySQL database.

    Args:
        donor: Validated donor dictionary.
    """
    insert_sql = """
        INSERT INTO donors (
            donor_id, state, hospital_id, blood_group,
            organ_type, hla_type, logged_datetime, viability_hours
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            state = VALUES(state),
            hospital_id = VALUES(hospital_id),
            blood_group = VALUES(blood_group),
            organ_type = VALUES(organ_type),
            hla_type = VALUES(hla_type),
            logged_datetime = VALUES(logged_datetime),
            viability_hours = VALUES(viability_hours);
    """
    with get_cursor(commit=True) as cursor:
        cursor.execute(
            insert_sql,
            (
                donor["donor_id"],
                donor["state"],
                donor["hospital_id"],
                donor["blood_group"],
                donor["organ_type"],
                donor["hla_type"],
                donor["logged_datetime"],
                donor["viability_hours"],
            ),
        )


def persist_scores(donor_id: str, ranked_list: list[dict[str, Any]]) -> None:
    """Store computed match scores in the MySQL scores table.

    Args:
        donor_id: Primary key of the donor.
        ranked_list: List of patient records with computed scores.
    """
    if not ranked_list:
        return

    score_sql = """
        INSERT INTO scores (
            patient_id, donor_id, urgency_score, match_score,
            wait_score, distance_score, total_score, computed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            urgency_score = VALUES(urgency_score),
            match_score = VALUES(match_score),
            wait_score = VALUES(wait_score),
            distance_score = VALUES(distance_score),
            total_score = VALUES(total_score),
            computed_at = NOW();
    """
    records = [
        (
            item["patient_id"],
            donor_id,
            item["urgency_score"],
            item["match_score"],
            item["wait_score"],
            item["distance_score"],
            item["total_score"],
        )
        for item in ranked_list
    ]

    with get_cursor(commit=True) as cursor:
        cursor.executemany(score_sql, records)


@api_bp.route("/patients", methods=["GET", "POST"])
def patients_collection() -> tuple[Response, int]:
    """List patients or register a new synthetic waitlist patient."""
    if request.method == "GET":
        try:
            with get_cursor(dictionary=True, commit=False) as cursor:
                if user_has_role("hospital"):
                    cursor.execute("SELECT * FROM patients WHERE hospital_id=%s ORDER BY registered_date DESC, patient_id", (session.get("hospital_id"),))
                else:
                    cursor.execute("SELECT * FROM patients ORDER BY registered_date DESC, patient_id")
                return jsonify(cursor.fetchall()), 200
        except MySQLError as exc:
            logger.error("Patient listing failed: %s", exc)
            return jsonify({"error": "Could not retrieve patients."}), 500

    if not user_has_role("admin", "coordinator", "hospital"):
        return jsonify({"error": "You do not have permission to register patients."}), 403
    patient, error = validate_patient_payload(request.get_json(silent=True))
    if error or patient is None:
        return jsonify({"error": error}), 400
    if user_has_role("hospital"):
        patient["hospital_id"] = session.get("hospital_id")
        if not patient["hospital_id"]:
            return jsonify({"error": "This hospital account is not linked to a hospital."}), 403
    columns = ("patient_id", "name", "age", "gender", "state", "hospital_id", "hospital_type",
               "blood_group", "organ_needed", "hla_type", "dialysis_status", "icu_level",
               "organ_failure_stage", "days_on_waitlist", "family_donor_relative", "registered_date")
    sql = f"INSERT INTO patients ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})"
    try:
        with get_cursor(commit=True) as cursor:
            cursor.execute(sql, tuple(patient[col] for col in columns))
        write_audit_event("PATIENT_REGISTERED", patient["patient_id"], {"organ_needed": patient["organ_needed"]})
        return jsonify({"message": "Patient registered successfully.", "patient_id": patient["patient_id"]}), 201
    except MySQLError as exc:
        if getattr(exc, "errno", None) == 1062:
            return jsonify({"error": f"Patient ID '{patient['patient_id']}' already exists."}), 409
        if getattr(exc, "errno", None) == 1452:
            return jsonify({"error": "Hospital ID does not exist. Select a hospital registered in the database."}), 400
        logger.error("Patient registration failed: %s", exc)
        return jsonify({"error": "Patient registration failed. Check database schema and hospital ID."}), 500


@api_bp.route("/patients/<patient_id>", methods=["PUT", "DELETE"])
def patient_item(patient_id: str) -> tuple[Response, int]:
    """Update or delete a patient record."""
    if not user_has_role("admin", "coordinator", "hospital"):
        return jsonify({"error": "You do not have permission to modify patient records."}), 403
    try:
        if user_has_role("hospital"):
            if request.method == "DELETE":
                return jsonify({"error": "Hospital users cannot delete patient records."}), 403
            with get_cursor(dictionary=True, commit=False) as cursor:
                cursor.execute("SELECT hospital_id FROM patients WHERE patient_id=%s", (patient_id,))
                owned = cursor.fetchone()
            if not owned or owned["hospital_id"] != session.get("hospital_id"):
                return jsonify({"error": "You can only update patients belonging to your hospital."}), 403
        if request.method == "DELETE":
            with get_cursor(commit=True) as cursor:
                cursor.execute("DELETE FROM patients WHERE patient_id = %s", (patient_id,))
                if cursor.rowcount == 0:
                    return jsonify({"error": "Patient not found."}), 404
            write_audit_event("PATIENT_DELETED", patient_id, {})
            return jsonify({"message": "Patient deleted."}), 200
        patient, error = validate_patient_payload(request.get_json(silent=True))
        if error or patient is None:
            return jsonify({"error": error}), 400
        if patient["patient_id"] != patient_id:
            return jsonify({"error": "patient_id in URL and body must match."}), 400
        if user_has_role("hospital"):
            patient["hospital_id"] = session.get("hospital_id")
        fields = ["name", "age", "gender", "state", "hospital_id", "hospital_type", "blood_group",
                  "organ_needed", "hla_type", "dialysis_status", "icu_level", "organ_failure_stage",
                  "days_on_waitlist", "family_donor_relative", "registered_date"]
        sql = "UPDATE patients SET " + ", ".join(f"{field} = %s" for field in fields) + " WHERE patient_id = %s"
        with get_cursor(commit=True) as cursor:
            cursor.execute(sql, tuple(patient[f] for f in fields) + (patient_id,))
            if cursor.rowcount == 0:
                cursor.execute("SELECT patient_id FROM patients WHERE patient_id = %s", (patient_id,))
                if not cursor.fetchone():
                    return jsonify({"error": "Patient not found."}), 404
        write_audit_event("PATIENT_UPDATED", patient_id, {})
        return jsonify({"message": "Patient updated."}), 200
    except MySQLError as exc:
        logger.error("Patient operation failed: %s", exc)
        return jsonify({"error": "Patient operation failed. Check hospital ID and database."}), 500


@api_bp.route("/donor", methods=["POST"])
def log_donor() -> tuple[Response, int]:
    """Log a newly registered donor, execute ranking pipeline, and store scores.

    Expected JSON body:
        {
            "donor_id": "D001",
            "state": "Maharashtra",
            "hospital_id": "H001",
            "blood_group": "A+",
            "organ_type": "Kidney",
            "hla_type": "A2,A24,B7,B44,DR4,DR7",
            "logged_datetime": "2026-09-16 10:00:00",
            "viability_hours": 24
        }

    Returns:
        JSON list of ranked candidate patients ordered by score descending.
    """
    if not user_has_role("admin", "coordinator"):
        return jsonify({"error": "Only administrators and coordinators can register donors."}), 403
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid request: Payload must be JSON."}), 400

    donor, err_msg = validate_donor_payload(payload)
    if err_msg or donor is None:
        return jsonify({"error": err_msg}), 400

    try:
        # 1. Save donor record and record the intake event
        save_donor_record(donor)
        write_audit_event("DONOR_REGISTERED", donor["donor_id"], {"organ_type": donor["organ_type"], "blood_group": donor["blood_group"]})

        # 2. Fetch patients from database
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT latitude, longitude FROM hospitals WHERE hospital_id=%s", (donor["hospital_id"],))
            donor_coords = cursor.fetchone() or {}
        donor.update(donor_coords)
        patients_df = fetch_active_patients_df()

        # 3. Generate ranked list using core scoring engine
        ranked_list = generate_ranked_list(donor, patients_df, weights=get_scoring_weights())

        # 4. Persist scores to database
        persist_scores(donor["donor_id"], ranked_list)
        write_audit_event("RANKING_GENERATED", donor["donor_id"], {"candidate_ids": [p["patient_id"] for p in ranked_list], "candidate_count": len(ranked_list)})

        # 5. Return ranked list as JSON
        return jsonify(ranked_list), 200

    except MySQLError as db_err:
        logger.error("Database error during donor logging: %s", db_err)
        return jsonify({
            "error": f"Database error: {db_err}. Please ensure MySQL is running and schema is initialized."
        }), 500
    except Exception as exc:
        logger.error("Unexpected error during donor logging: %s", exc)
        return jsonify({"error": f"Internal server error: {exc}"}), 500


def apply_demo_priority_rules(ranked: list[dict[str, Any]], donor: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply explicitly labelled prototype policy signals after medical compatibility filtering.

    These small configurable-style signals are illustrative only; they are not clinical guidance.
    They never make an incompatible patient eligible.
    """
    for item in ranked:
        same_hospital = str(item.get("hospital_id", "")) == str(donor.get("hospital_id", ""))
        family_relative = str(item.get("family_donor_relative", "No")).lower() == "yes"
        item["special_priority"] = {
            "same_hospital": same_hospital,
            "family_donor_relative_recorded": family_relative,
            "policy_note": "Informational flags only; no automatic clinical priority is assigned."
        }
    return ranked


@api_bp.route("/allocation/urgent-override", methods=["POST"])
def urgent_override() -> tuple[Response, int]:
    """Record coordinator-approved simulated urgent ordering for a compatible candidate."""
    if not user_has_role("admin", "coordinator"):
        return jsonify({"error": "Only an administrator or coordinator can issue an urgent override."}), 403
    data = request.get_json(silent=True) or {}
    donor_id = str(data.get("donor_id", "")).strip()
    patient_id = str(data.get("patient_id", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if not donor_id or not patient_id or len(reason) < 12:
        return jsonify({"error": "donor_id, patient_id and a reason of at least 12 characters are required."}), 400
    if user_has_role("hospital"):
        return jsonify({"error": "Hospital users cannot access national comparison results."}), 403
    try:
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT * FROM donors WHERE donor_id=%s", (donor_id,))
            donor = cursor.fetchone()
            cursor.execute("SELECT * FROM patients WHERE patient_id=%s", (patient_id,))
            patient = cursor.fetchone()
        if not donor or not patient:
            return jsonify({"error": "Donor or patient was not found."}), 404
        if patient.get("blood_group") != donor.get("blood_group") or patient.get("organ_needed") != donor.get("organ_type"):
            return jsonify({"error": "Override rejected: patient does not pass the existing organ and blood-group compatibility filters."}), 409
        with get_cursor(commit=True) as cursor:
            cursor.execute("INSERT INTO urgent_overrides (donor_id, patient_id, reason, approved_by, created_at) VALUES (%s,%s,%s,%s,NOW())",
                           (donor_id, patient_id, reason, session.get("username")))
        write_audit_event("URGENT_OVERRIDE_RECORDED", donor_id, {"patient_id": patient_id, "reason": reason, "approved_by": session.get("username"), "prototype_only": True})
        return jsonify({"message": "Urgent override recorded. Regenerate ranking to apply the simulated ordering.", "donor_id": donor_id, "patient_id": patient_id}), 201
    except MySQLError:
        logger.exception("Urgent override could not be saved")
        return jsonify({"error": "Urgent override table is not ready. Run migration_priority_rules.sql."}), 500


@api_bp.route("/patients/ranked/<donor_id>", methods=["GET"])
def get_ranked_patients(donor_id: str) -> tuple[Response, int]:
    """Retrieve or re-compute ranked patient allocation list for an existing donor.

    Args:
        donor_id: Identifier of the donor record.

    Returns:
        JSON list of ranked candidate patients.
    """
    if user_has_role("hospital"):
        return jsonify({"error": "Hospital users cannot access national donor rankings."}), 403
    clean_id = str(donor_id).strip()
    if not clean_id:
        return jsonify({"error": "Missing or invalid 'donor_id' parameter."}), 400

    try:
        # 1. Look up donor record
        donor_query = "SELECT * FROM donors WHERE donor_id = %s"
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute(donor_query, (clean_id,))
            donor = cursor.fetchone()

        if not donor:
            return jsonify({"error": f"Donor '{clean_id}' was not found."}), 404

        # Convert logged_datetime to string if necessary
        if isinstance(donor.get("logged_datetime"), datetime):
            donor["logged_datetime"] = donor["logged_datetime"].strftime("%Y-%m-%d %H:%M:%S")

        # 2. Query patients and generate ranking
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT latitude, longitude FROM hospitals WHERE hospital_id=%s", (donor["hospital_id"],))
            donor.update(cursor.fetchone() or {})
        patients_df = fetch_active_patients_df()
        ranked_list = generate_ranked_list(donor, patients_df, weights=get_scoring_weights())
        ranked_list = apply_demo_priority_rules(ranked_list, donor)
        # A coordinator override can only reorder a candidate already admitted by compatibility filters.
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT patient_id, reason, approved_by FROM urgent_overrides WHERE donor_id=%s ORDER BY created_at DESC LIMIT 1", (clean_id,))
            active_override = cursor.fetchone()
        if active_override:
            chosen = next((p for p in ranked_list if str(p.get("patient_id")) == str(active_override["patient_id"])), None)
            if chosen:
                ranked_list.remove(chosen)
                chosen["urgent_override"] = True
                chosen["override_reason"] = active_override["reason"]
                chosen["override_approved_by"] = active_override["approved_by"]
                ranked_list.insert(0, chosen)
            for candidate in ranked_list:
                candidate.setdefault("urgent_override", False)

        # 3. Update persisted scores
        persist_scores(clean_id, ranked_list)
        write_audit_event("RANKING_GENERATED", clean_id, {"candidate_ids": [p["patient_id"] for p in ranked_list], "candidate_count": len(ranked_list)})

        return jsonify(ranked_list), 200

    except MySQLError as db_err:
        logger.error("Database error during ranking lookup: %s", db_err)
        return jsonify({
            "error": f"Database error: {db_err}. Please ensure MySQL is running and schema is initialized."
        }), 500
    except Exception as exc:
        logger.error("Unexpected error during ranking lookup: %s", exc)
        return jsonify({"error": f"Internal server error: {exc}"}), 500


@api_bp.route("/dashboard/summary", methods=["GET"])
def dashboard_summary() -> tuple[Response, int]:
    """Return aggregate prototype metrics; hospital users receive own-site count only."""
    if user_has_role("hospital"):
        try:
            with get_cursor(dictionary=True, commit=False) as cursor:
                cursor.execute("SELECT COUNT(*) AS total_patients FROM patients WHERE hospital_id=%s", (session.get("hospital_id"),))
                count = cursor.fetchone() or {}
            return jsonify({"patients": int(count.get("total_patients", 0)), "donors": 0, "score_records": 0, "audit_events": 0, "scope": "own_hospital"}), 200
        except MySQLError:
            return jsonify({"error": "Could not load hospital dashboard."}), 500
    try:
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT COUNT(*) AS total_patients FROM patients")
            patients = cursor.fetchone() or {}
            cursor.execute("SELECT COUNT(*) AS total_donors FROM donors")
            donors = cursor.fetchone() or {}
            cursor.execute("SELECT COUNT(*) AS total_scores FROM scores")
            scores = cursor.fetchone() or {}
            cursor.execute("SELECT COUNT(*) AS total_audit_events FROM audit_logs")
            audit = cursor.fetchone() or {}
            cursor.execute("SELECT organ_needed AS organ, COUNT(*) AS count FROM patients GROUP BY organ_needed ORDER BY organ_needed")
            by_organ = cursor.fetchall()
            cursor.execute("SELECT state, COUNT(*) AS count FROM patients GROUP BY state ORDER BY state")
            by_state = cursor.fetchall()
        return jsonify({
            "patients": int(patients.get("total_patients", 0)),
            "donors": int(donors.get("total_donors", 0)),
            "score_records": int(scores.get("total_scores", 0)),
            "audit_events": int(audit.get("total_audit_events", 0)),
            "patients_by_organ": by_organ,
            "patients_by_state": by_state,
            "notice": "Aggregate counts from synthetic academic prototype data only."
        }), 200
    except MySQLError as exc:
        logger.error("Dashboard summary failed: %s", exc)
        return jsonify({"error": "Could not load dashboard summary. Check that the audit migration has been applied."}), 500


@api_bp.route("/audit-logs", methods=["GET"])
def list_audit_logs() -> tuple[Response, int]:
    """Return recent audit events to administrators and coordinators only."""
    if not user_has_role("admin", "coordinator"):
        return jsonify({"error": "Only administrators and coordinators can view system audit logs."}), 403
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    except ValueError:
        return jsonify({"error": "limit must be an integer."}), 400
    try:
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute(
                "SELECT audit_id, event_type, entity_id, details_json, created_at "
                "FROM audit_logs ORDER BY created_at DESC, audit_id DESC LIMIT %s", (limit,)
            )
            rows = cursor.fetchall()
        for row in rows:
            if isinstance(row.get("created_at"), datetime):
                row["created_at"] = row["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        return jsonify(rows), 200
    except MySQLError as exc:
        logger.error("Audit log retrieval failed: %s", exc)
        return jsonify({"error": "Could not retrieve audit logs. Apply the audit-log migration first."}), 500


@api_bp.route("/comparison/<donor_id>", methods=["GET"])
def compare_rankings(donor_id: str) -> tuple[Response, int]:
    """Compare national-pool ranking with a clearly labelled state-restricted baseline.

    This is a project simulation, not a representation of every state's real policy.
    """
    if user_has_role("hospital"):
        return jsonify({"error": "Hospital users cannot access national comparison results."}), 403
    try:
        with get_cursor(dictionary=True, commit=False) as cursor:
            cursor.execute("SELECT * FROM donors WHERE donor_id = %s", (donor_id.strip(),))
            donor = cursor.fetchone()
        if not donor:
            return jsonify({"error": "Donor not found."}), 404
        if isinstance(donor.get("logged_datetime"), datetime):
            donor["logged_datetime"] = donor["logged_datetime"].strftime("%Y-%m-%d %H:%M:%S")
        all_patients = fetch_active_patients_df()
        national = generate_ranked_list(donor, all_patients, weights=get_scoring_weights())
        state_patients = all_patients[all_patients["state"].astype(str) == str(donor["state"])]
        state_only = generate_ranked_list(donor, state_patients, weights=get_scoring_weights())
        national_positions = {p["patient_id"]: i + 1 for i, p in enumerate(national)}
        state_positions = {p["patient_id"]: i + 1 for i, p in enumerate(state_only)}
        common_ids = set(national_positions) & set(state_positions)
        changed = [pid for pid in common_ids if national_positions[pid] != state_positions[pid]]
        return jsonify({
            "donor_id": donor_id,
            "baseline_name": "Same-state-only simulation (not actual state policy)",
            "national_candidate_count": len(national),
            "state_only_candidate_count": len(state_only),
            "national_ranking": [{"patient_id": p["patient_id"], "name": p.get("name"), "rank": i + 1, "total_score": p.get("total_score")} for i, p in enumerate(national)],
            "state_only_ranking": [{"patient_id": p["patient_id"], "name": p.get("name"), "rank": i + 1, "total_score": p.get("total_score")} for i, p in enumerate(state_only)],
            "common_candidates_with_changed_rank": len(changed),
            "common_candidates_compared": len(common_ids),
            "rank_change_rate_percent": round((len(changed) / len(common_ids) * 100), 2) if common_ids else 0.0,
            "method_note": "Ranks are compared only for candidates appearing in both lists. This controlled same-state restriction is an illustrative baseline, not a claim about any real state's allocation rules."
        }), 200
    except MySQLError as exc:
        logger.error("Ranking comparison failed: %s", exc)
        return jsonify({"error": "Could not compare rankings."}), 500


@api_bp.route("/allocation/confirm", methods=["POST"])
def confirm_allocation() -> tuple[Response, int]:
    """Demo-only atomic allocation claim; row locks prevent double assignment."""
    if not user_has_role("admin", "coordinator"):
        return jsonify({"error": "Only coordinators or admins can confirm a simulated allocation."}), 403
    data = request.get_json(silent=True) or {}
    donor_id, patient_id = str(data.get("donor_id", "")).strip(), str(data.get("patient_id", "")).strip()
    if not donor_id or not patient_id:
        return jsonify({"error": "donor_id and patient_id are required."}), 400
    try:
        with get_cursor(dictionary=True, commit=True) as cursor:
            cursor.execute("SELECT donor_id, organ_type, blood_group FROM donors WHERE donor_id=%s FOR UPDATE", (donor_id,))
            donor = cursor.fetchone()
            if not donor: return jsonify({"error": "Donor not found."}), 404
            cursor.execute("SELECT patient_id, organ_needed, blood_group FROM patients WHERE patient_id=%s FOR UPDATE", (patient_id,))
            patient = cursor.fetchone()
            if not patient: return jsonify({"error": "Patient not found."}), 404
            if donor["organ_type"] != patient["organ_needed"] or donor["blood_group"] != patient["blood_group"]:
                return jsonify({"error": "Patient fails the prototype's exact organ/blood compatibility filter."}), 400
            cursor.execute("SELECT allocation_id FROM allocations WHERE donor_id=%s OR patient_id=%s FOR UPDATE", (donor_id, patient_id))
            if cursor.fetchone(): return jsonify({"error": "This donor or patient already has a confirmed allocation."}), 409
            cursor.execute("INSERT INTO allocations (donor_id, patient_id, confirmed_by, status, created_at) VALUES (%s,%s,%s,'SIMULATED_CONFIRMED',NOW())", (donor_id, patient_id, session.get("username")))
        write_audit_event("SIMULATED_ALLOCATION_CONFIRMED", donor_id, {"patient_id": patient_id, "confirmed_by": session.get("username")})
        return jsonify({"message": "Simulated allocation recorded atomically.", "donor_id": donor_id, "patient_id": patient_id}), 201
    except MySQLError as exc:
        if getattr(exc, "errno", None) == 1062:
            return jsonify({"error": "Donor or patient already has an allocation."}), 409
        logger.exception("Allocation confirmation failed")
        return jsonify({"error": "Could not confirm simulated allocation. Check migration and database."}), 500
