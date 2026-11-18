"""Idempotent data ingestion script for hospitals, patients, and donors."""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db.connection import get_connection, get_cursor

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def execute_sql_file(file_path: Path, include_db: bool = True) -> None:
    """Read and execute all semicolon-separated SQL statements in a file.

    Args:
        file_path: Path to the SQL file.
        include_db: Whether to connect directly to the target database.
    """
    if not file_path.exists():
        logger.error("SQL file not found: %s", file_path)
        return

    logger.info("Executing SQL file: %s", file_path.name)
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # Split commands by semicolon, ignoring empty lines and comments
    statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]

    conn = get_connection(include_db=include_db)
    try:
        cursor = conn.cursor()
        for statement in statements:
            # Skip empty or pure comment statements
            cleaned = "\n".join(
                line for line in statement.splitlines() if not line.strip().startswith("--")
            ).strip()
            if cleaned:
                cursor.execute(cleaned)
        conn.commit()
        cursor.close()
        logger.info("Successfully executed %s", file_path.name)
    finally:
        if conn.is_connected():
            conn.close()


def load_all_data(
    patients_csv_path: str | Path | None = None,
    donors_csv_path: str | Path | None = None,
) -> None:
    """Load hospitals, patients, and donors from CSV files into MySQL idempotently.

    Args:
        patients_csv_path: Optional path to patients CSV. Defaults to data/patients_cleaned.csv.
        donors_csv_path: Optional path to donors CSV. Defaults to data/donors.csv.
    """
    if patients_csv_path is None:
        patients_csv_path = BASE_DIR / "data" / "patients_cleaned.csv"
    if donors_csv_path is None:
        donors_csv_path = BASE_DIR / "data" / "donors.csv"

    patients_path = Path(patients_csv_path)
    donors_path = Path(donors_csv_path)

    if not patients_path.exists():
        raise FileNotFoundError(f"Patients CSV not found at: {patients_path}")
    if not donors_path.exists():
        raise FileNotFoundError(f"Donors CSV not found at: {donors_path}")

    logger.info("Reading CSV data with pandas...")
    patients_df = pd.read_csv(patients_path)
    donors_df = pd.read_csv(donors_path)

    with get_cursor(include_db=True, commit=True) as cursor:
        # 1. Ensure states exist and build state_name -> state_id lookup
        cursor.execute("SELECT state_id, state_name FROM states")
        state_rows = cursor.fetchall()
        state_map = {row["state_name"]: row["state_id"] for row in state_rows}

        # If states are missing, seed any new states from datasets
        all_states = sorted(
            set(patients_df["state"].dropna().unique()).union(
                set(donors_df["state"].dropna().unique())
            )
        )
        for state_name in all_states:
            if state_name not in state_map:
                cursor.execute(
                    "INSERT IGNORE INTO states (state_name) VALUES (%s)",
                    (state_name,),
                )
                cursor.execute(
                    "SELECT state_id FROM states WHERE state_name = %s",
                    (state_name,),
                )
                res = cursor.fetchone()
                if res:
                    state_map[state_name] = res["state_id"]

        logger.info("States mapped: %s", state_map)

        # 2. Derive unique hospitals from CSVs
        # Extract hospital_id, state, hospital_type from patients_df
        hospitals_subset = patients_df[["hospital_id", "state", "hospital_type"]].drop_duplicates()
        hospital_insert_sql = """
            INSERT INTO hospitals (hospital_id, hospital_name, state_id, hospital_type)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                hospital_name = VALUES(hospital_name),
                state_id = VALUES(state_id),
                hospital_type = VALUES(hospital_type);
        """

        hospital_records = []
        for _, row in hospitals_subset.iterrows():
            h_id = str(row["hospital_id"]).strip()
            state = str(row["state"]).strip()
            h_type = str(row["hospital_type"]).strip()
            s_id = state_map.get(state)
            if not s_id:
                raise ValueError(f"State '{state}' not mapped for hospital '{h_id}'")
            h_name = f"Hospital {h_id} ({state})"
            hospital_records.append((h_id, h_name, s_id, h_type))

        cursor.executemany(hospital_insert_sql, hospital_records)
        logger.info("Inserted/updated %d hospitals.", len(hospital_records))

        # 3. Ingest patients idempotently
        patient_insert_sql = """
            INSERT INTO patients (
                patient_id, name, age, gender, state, hospital_id, hospital_type,
                blood_group, organ_needed, hla_type, dialysis_status, icu_level,
                organ_failure_stage, days_on_waitlist, family_donor_relative, registered_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                age = VALUES(age),
                gender = VALUES(gender),
                state = VALUES(state),
                hospital_id = VALUES(hospital_id),
                hospital_type = VALUES(hospital_type),
                blood_group = VALUES(blood_group),
                organ_needed = VALUES(organ_needed),
                hla_type = VALUES(hla_type),
                dialysis_status = VALUES(dialysis_status),
                icu_level = VALUES(icu_level),
                organ_failure_stage = VALUES(organ_failure_stage),
                days_on_waitlist = VALUES(days_on_waitlist),
                family_donor_relative = VALUES(family_donor_relative),
                registered_date = VALUES(registered_date);
        """

        patient_records = []
        for _, row in patients_df.iterrows():
            patient_records.append((
                str(row["patient_id"]).strip(),
                str(row["name"]).strip(),
                int(row["age"]),
                str(row["gender"]).strip(),
                str(row["state"]).strip(),
                str(row["hospital_id"]).strip(),
                str(row["hospital_type"]).strip(),
                str(row["blood_group"]).strip(),
                str(row["organ_needed"]).strip(),
                str(row["hla_type"]).strip(),
                str(row["dialysis_status"]).strip(),
                str(row["icu_level"]).strip(),
                int(row["organ_failure_stage"]),
                int(row["days_on_waitlist"]),
                str(row["family_donor_relative"]).strip(),
                str(row["registered_date"]).strip(),
            ))

        cursor.executemany(patient_insert_sql, patient_records)
        logger.info("Inserted/updated %d patients.", len(patient_records))

        # 4. Ingest donors idempotently
        donor_insert_sql = """
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

        donor_records = []
        for _, row in donors_df.iterrows():
            donor_records.append((
                str(row["donor_id"]).strip(),
                str(row["state"]).strip(),
                str(row["hospital_id"]).strip(),
                str(row["blood_group"]).strip(),
                str(row["organ_type"]).strip(),
                str(row["hla_type"]).strip(),
                str(row["logged_datetime"]).strip(),
                int(row["viability_hours"]),
            ))

        cursor.executemany(donor_insert_sql, donor_records)
        logger.info("Inserted/updated %d donors.", len(donor_records))

    logger.info("Data ingestion completed successfully.")


if __name__ == "__main__":
    schema_path = BASE_DIR / "db" / "schema.sql"
    seed_states_path = BASE_DIR / "db" / "seed_states.sql"

    # Initialize schema and states first
    try:
        execute_sql_file(schema_path, include_db=False)
        execute_sql_file(seed_states_path, include_db=True)
    except Exception as exc:
        logger.warning(
            "Could not run schema/seed SQL directly via connection: %s. "
            "Proceeding with data ingestion assuming schema is already initialized.",
            exc,
        )

    load_all_data()
