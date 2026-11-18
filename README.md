# Unified Organ Allocation System

A Flask + MySQL academic prototype for cross-state deceased-donor organ matching and patient ranking in India. The application uses **synthetic demonstration records only**. It is a software-engineering prototype, not a clinically validated allocation system and must not be used to make or execute real organ-allocation decisions.

## Contents

- [Project overview](#project-overview)
- [Features](#features)
- [Technology stack](#technology-stack)
- [Architecture and request flow](#architecture-and-request-flow)
- [Repository structure](#repository-structure)
- [Requirements](#requirements)
- [Local setup on Windows](#local-setup-on-windows)
- [Database setup and migrations](#database-setup-and-migrations)
- [Demo login accounts and roles](#demo-login-accounts-and-roles)
- [Run the application](#run-the-application)
- [Scoring and matching logic](#scoring-and-matching-logic)
- [API reference](#api-reference)
- [Tests](#tests)
- [Security, privacy and limitations](#security-privacy-and-limitations)
- [Troubleshooting](#troubleshooting)

## Project overview

The system accepts donor details, filters the synthetic patient waitlist for exact organ and blood-group compatibility, calculates a weighted score for eligible candidates, sorts the candidates, and displays the resulting ranked list. It also provides patient management, role-based access, audit events, scoring-policy configuration, a national-versus-same-state comparison simulation, geographic distance scoring when coordinates are present, and a concurrency-safe simulated confirmation endpoint.

The system's normal result is a **ranking**. A first-ranked patient is a *Primary Match*, not an allocated organ. The separate confirmation endpoint records an explicitly labelled simulated claim for software demonstration only.

## Features

- Donor registration and ranked candidate generation.
- Exact blood-group and organ-type eligibility filter.
- Weighted urgency, HLA, waiting-time and distance scoring.
- Tiebreaker handling and coordinator escalation flag.
- Patient registration, listing, update and deletion (role dependent).
- Admin, coordinator and hospital login using password hashes and Flask sessions.
- Hospital accounts linked to a single `hospital_id`; hospital patient queries are scoped to that hospital.
- Admin/coordinator urgent-override action directly in the ranking results table for compatible synthetic cases; requires a reason and refreshes the ranking.
- Informational same-hospital and family-donor-relative indicators. These flags do not independently confer medical priority.
- Configurable scoring weights, with a 100% total validation.
- Dashboard counts, audit events and a same-state-only comparison simulation.
- Haversine straight-line distance when both hospital locations have coordinates.
- Transactional simulated allocation confirmation with row locks and unique donor/patient constraints.

## Technology stack

| Layer | Technology | Responsibility |
|---|---|---|
| User interface | HTML, Bootstrap 5, vanilla JavaScript | Login, role-aware dashboard, forms, tables and API calls |
| Web/API | Python, Flask | Page routing, authentication, request validation and JSON endpoints |
| Business logic | Python, Pandas | Compatibility filtering, scoring, sorting and tiebreakers |
| Persistence | MySQL, InnoDB, mysql-connector-python | Users, hospitals, patients, donors, scores, policies, audit and simulated claims |
| Tests | Pytest | Scoring and API validation tests |

## Architecture and request flow

```text
Browser (templates/index.html + static/script.js)
                 |
                 | HTTP / JSON requests
                 v
          Flask application (app.py)
                 |
                 v
          API Blueprint (routes.py)
          |          |             |
          |          |             +--> Authentication / role checks
          |          +----------------> MySQL access (db/connection.py)
          |
          +--> Scoring engine (scoring/engine.py)
                         |
                         +--> eligible candidates + component scores + ranking
                                      |
                                      v
                             MySQL scores table
                                      |
                                      v
                            JSON response to browser
```

### Typical donor-ranking flow

1. An admin or coordinator signs in. Flask stores the user's ID, username, role and (for hospital accounts) hospital ID in the session.
2. The browser submits donor data to `POST /api/donor`.
3. `routes.py` validates the payload and stores the donor record.
4. Patient records and the donor/patient hospitals' coordinates are loaded from MySQL.
5. `scoring/engine.py` filters incompatible candidates and calculates component and total scores.
6. The route persists the scores and writes audit events.
7. The ranked JSON response is rendered in the browser as Primary Match and Standby candidates.

### Module responsibilities

- `app.py`: loads environment configuration, creates the Flask application, registers the API Blueprint and serves the login/dashboard pages.
- `routes.py`: authentication, role checks, validation, database operations, donor/patient workflows, ranking orchestration, audit logging and API responses.
- `scoring/engine.py`: matching and scoring logic; kept separate from Flask so the scoring functions can be tested independently.
- `db/connection.py`: reads database connection values from environment variables and provides cursor/transaction handling with commit or rollback.
- `db/load_data.py`: initializes the base schema and imports the supplied synthetic CSV records.
- `templates/`: server-rendered HTML pages.
- `static/script.js`: calls the API using `fetch`, handles login state and role-specific interface visibility, and renders returned data.

## Repository structure

```text
organ-allocation-prototype/
├── app.py                         # Flask app creation and local entry point
├── routes.py                      # /api routes, auth, role checks and workflows
├── scoring/
│   ├── __init__.py
│   └── engine.py                  # Eligibility, scoring, sorting and tiebreakers
├── db/
│   ├── connection.py              # MySQL connection and transaction helper
│   ├── schema.sql                 # Base database and core tables
│   ├── seed_states.sql            # State seed data
│   ├── load_data.py               # Schema setup and synthetic CSV ingestion
│   ├── migration_users.sql        # User/authentication table
│   ├── migration_audit_log.sql    # Audit log table
│   ├── migration_scoring_policy.sql # Configurable scoring weights
│   ├── migration_priority_rules.sql # Urgent override records
│   └── migration_distance_concurrency_roles.sql # Hospital linkage, coordinates and allocations
├── data/
│   ├── patients_cleaned.csv       # Synthetic patient waitlist
│   └── donors.csv                 # Synthetic donor records
├── templates/
│   ├── login.html                 # Login page
│   └── index.html                 # Main dashboard
├── static/
│   └── script.js                 # Browser-side API and UI logic
├── tests/
│   ├── test_engine.py             # Scoring tests
│   └── test_api.py                # API and validation tests
├── create_admin.py                # Interactive first-admin setup
├── requirements.txt
├── Procfile                       # Production WSGI start command
├── .env.example                   # Environment-variable template
├── LOGIN_SETUP.md                 # Login setup notes
├── PRIORITY_AND_USERS_SETUP.md    # Role and priority setup notes
└── README.md
```

## Requirements

- Python 3.11 or newer (use a version supported by the deployment host).
- MySQL 8.x with InnoDB and permission to create/alter tables.
- MySQL Workbench is recommended for Windows users, but not required.
- Git is recommended for version control and deployment.

## Local setup on Windows

Open PowerShell in the project root (the folder containing `app.py`).

### 1. Create and activate a virtual environment

```powershell
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

The execution-policy command applies only to the current PowerShell process. Alternatively, use Command Prompt and run `venv\\Scripts\\activate.bat`.

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Create the environment file

Copy `.env.example` to `.env` and update the values. Never commit `.env` to Git.

```ini
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=your_mysql_user
DB_PASSWORD=your_mysql_password
DB_NAME=organ_allocation
SECRET_KEY=replace-with-a-long-random-secret
APP_ENV=development
FLASK_PORT=5000
FLASK_DEBUG=True
```

Use a long, random, private `SECRET_KEY`. Do not use the example value for a public deployment.

## Database setup and migrations

### Fresh database

For a brand-new local database, start MySQL and run:

```powershell
python db/load_data.py
```

The loader executes the base schema and seed script, then imports the supplied synthetic CSV data. It is intended to be re-runnable for the base data load.

### Existing database (the normal upgrade path)

If your existing local application and data already work, **do not rerun the loader or drop/recreate the database**. Apply only migrations that have not already been applied, in this order:

1. `db/migration_users.sql`
2. `db/migration_audit_log.sql`
3. `db/migration_scoring_policy.sql`
4. `db/migration_priority_rules.sql`
5. `db/migration_distance_concurrency_roles.sql`

Run each file once in MySQL Workbench after selecting the `organ_allocation` schema. The last migration checks for missing columns using `information_schema`, so it does not rely on `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (unsupported by some MySQL versions). It also creates the `allocations` table used by the simulated confirmation route. If you have already manually added `users.hospital_id`, `hospitals.latitude` and `hospitals.longitude`, the migration should leave those columns in place and add any missing foreign key/table objects.

If a migration was partially run, inspect the relevant objects before rerunning it. Do not repeatedly execute a failed SQL script blindly. Back up the database before schema changes.

### Link a hospital account

Every account with role `hospital` must have a valid hospital ID that exists in `hospitals.hospital_id`. Example:

```sql
UPDATE users
SET hospital_id = 'H001'
WHERE username = 'hospital1' AND role = 'hospital';

SELECT username, role, hospital_id FROM users;
```

Replace `H001` with an ID returned by `SELECT hospital_id FROM hospitals;`. A hospital account without a valid linked ID should not be used.

### Add hospital coordinates

The migration adds nullable `latitude` and `longitude` fields to `hospitals`. Populate them with verified coordinates for each synthetic hospital. Example only (replace with correct coordinates):

```sql
UPDATE hospitals
SET latitude = 30.3398, longitude = 76.3869
WHERE hospital_id = 'H001';
```

Do not copy this example coordinate to every hospital. Missing coordinates cause the scoring engine to use its documented same-state fallback rather than geographic distance.

## Demo login accounts and roles

The login page begins with a **Sign in as** dropdown containing **Admin**, **Coordinator** and **Hospital**. The selected role is sent with the login request and must match the role stored for that username in the database. The application has three roles: **Admin**, **Coordinator** and **Hospital**. The following are the demonstration accounts configured for the local demo database.

> **Credential visibility:** Anyone who can read this README can see the coordinator and hospital demo credentials. Keep the GitHub repository private if you intend to share these credentials only with selected people. Change or replace these demo passwords before making the repository public or using the accounts in a deployed environment.

### Coordinator demo login

| Field | Value |
|---|---|
| Username | `coordinator1` |
| Password | `Coordinator@123` |
| Role | `coordinator` |

The coordinator manages donor registration and allocation operations. This role can register donors, generate national rankings, review candidates, record simulated urgent overrides, view audit events and confirm simulated allocations.

### Hospital demo login

| Field | Value |
|---|---|
| Username | `hospital1` |
| Password | `Hospital@123` |
| Role | `hospital` |
| Linked hospital ID | `H001` |

The hospital account is linked to hospital `H001`. It can register patients and view/update records belonging to that hospital. It cannot register donors, generate national rankings, change scoring weights or view system-wide audit logs.

The linked hospital ID must exist in the `hospitals` table. For another database, verify the hospital ID before linking or using the account.

### Administrator account
username - Admin
password- Admin123abc



### Role permissions implemented in the backend

| Capability | Admin | Coordinator | Hospital |
|---|:---:|:---:|:---:|
| View overall dashboard | Yes | Yes | Own-hospital patient count only |
| List patients | All | All | Linked hospital only |
| Register patients | Yes | Yes | Yes, linked hospital only |
| Update patients | Yes | Yes | Own-hospital records only |
| Delete patients | Yes | Yes | No |
| Register donors / generate rankings | Yes | Yes | No |
| Record urgent override | Yes | Yes | No |
| Change scoring weights | Yes | Yes (API permission) | No |
| View audit log API | Yes | Yes | No |
| Create/list user accounts | Yes | No | No |
| Confirm simulated allocation | Yes | Yes | No |

The browser interface hides controls according to role, and the API also enforces role checks for protected operations. On the Ranking Results table, Admin and Coordinator users see an **Override** action for each compatible candidate. The action asks for a reason of at least 12 characters, calls `POST /api/allocation/urgent-override`, then reloads the donor ranking. The selected candidate is displayed as overridden when the saved override is applied. Hospital users do not see this action. Hospital access is scoped to its linked hospital for patient listing and changes. Admin/coordinator accounts are not tied to a hospital.

## Run the application

With the virtual environment active and MySQL running:

```powershell
python app.py
```

Open `http://127.0.0.1:5000` in a browser. Sign in with an account configured in the database. For the configured local demonstration database, use the Coordinator or Hospital demo credentials listed above. Administrator credentials are provided separately by the project owner.

Stop the local server with `Ctrl+C` in the terminal.

## Scoring and matching logic

### Eligibility filter

A patient enters the candidate list only when both conditions match:

- `patient.blood_group == donor.blood_group`
- `patient.organ_needed == donor.organ_type`

This is the prototype's simplified compatibility filter, not a complete clinical compatibility assessment.

### Weighted score

The default weights are:

\[
S = 0.40U + 0.30M + 0.20W + 0.10D
\]

Where:

- `U`: urgency score (organ-failure stage, ICU level and the kidney dialysis factor implemented by the engine).
- `M`: HLA allele-overlap score.
- `W`: normalized waiting-time score relative to the eligible candidate pool.
- `D`: distance score.

Weights can be changed through the scoring-policy UI/API and must total 100%. Changes apply to future rankings. The default values and any configured values are experimental project parameters, not clinically approved policy.

### Distance

When both donor and patient hospital coordinates are available, the engine calculates Haversine straight-line distance and maps it to a prototype score (100 at 0 km, decreasing linearly to 0 at 1,000 km). If coordinates are missing, it falls back to the same-state/different-state approximation. This is not road distance, travel duration, transport feasibility or organ viability modelling.

### Tiebreakers and priority indicators

The engine applies its sequential tiebreaker rules after score calculation. Same-hospital and family-donor-relative values are displayed as informational flags; they do not independently make an incompatible patient eligible or automatically add a priority bonus. A recorded urgent override is a coordinator/admin-controlled simulation for a compatible candidate and is written to the audit log.

### Concurrency-safe simulated confirmation

`POST /api/allocation/confirm` locks the selected donor and patient rows in a transaction, rechecks the prototype's compatibility conditions and inserts a record in `allocations`. Unique constraints prevent a donor or patient from being used in more than one simulated confirmation. This is a demonstration of database transaction/concurrency handling, not a real allocation operation.

## API reference

All API routes are under `/api`. Except for login, they require an authenticated session cookie. JSON endpoints return JSON responses and standard HTTP status codes.

| Method | Endpoint | Purpose / access |
|---|---|---|
| `POST` | `/api/auth/login` | Authenticate with selected role, username and password; public |
| `POST` | `/api/auth/logout` | Clear current session |
| `GET` | `/api/auth/me` | Return current username, role and linked hospital ID |
| `GET`, `POST` | `/api/users` | List/create users; admin only. Creation supports coordinator/hospital roles |
| `GET`, `PUT` | `/api/scoring-weights` | Read or update policy weights; update requires admin/coordinator |
| `GET`, `POST` | `/api/patients` | List/register patients; hospital list is scoped to its linked hospital |
| `PUT`, `DELETE` | `/api/patients/<patient_id>` | Update/delete patient; hospital can update own records but cannot delete |
| `POST` | `/api/donor` | Register donor, generate and persist ranking; admin/coordinator |
| `GET` | `/api/patients/ranked/<donor_id>` | Retrieve/recompute ranked candidates; not hospital role |
| `POST` | `/api/allocation/urgent-override` | Record reasoned override for compatible candidate; admin/coordinator |
| `POST` | `/api/allocation/confirm` | Record concurrency-safe simulated confirmation; admin/coordinator |
| `GET` | `/api/dashboard/summary` | Aggregate dashboard; hospital receives own patient count only |
| `GET` | `/api/audit-logs?limit=50` | Recent audit events; admin/coordinator |
| `GET` | `/api/comparison/<donor_id>` | National vs same-state-only simulation; not hospital role |

### Example: login

```json
POST /api/auth/login
Content-Type: application/json

{"role":"admin","username":"admin-user","password":"your-password"}
```

### Example: create a patient

The patient JSON must contain the fields required by `validate_patient_payload` in `routes.py`, including patient ID, demographic fields, state, hospital ID, blood group, required organ, HLA type, urgency/ICU information and waitlist days. Use values matching the database ENUMs and an existing hospital ID. A hospital user's hospital ID is overwritten by the server session's linked hospital ID.

### Example: register a donor

```json
POST /api/donor
Content-Type: application/json

{
  "donor_id": "D-DEMO-001",
  "state": "Punjab",
  "hospital_id": "H001",
  "blood_group": "O+",
  "organ_type": "Kidney",
  "hla_type": "A2,A24,B7,B44,DR4,DR7",
  "logged_datetime": "2026-11-18 10:00:00",
  "viability_hours": 24
}
```

Use only synthetic IDs and values that exist in the database. A duplicate donor ID may update the donor record according to the current save routine; review the response and database before using the example repeatedly.

### Example: urgent override

```json
POST /api/allocation/urgent-override
Content-Type: application/json

{
  "donor_id": "D-DEMO-001",
  "patient_id": "P-DEMO-001",
  "reason": "Synthetic demonstration case requiring coordinator review."
}
```

The patient must pass the existing exact organ and blood-group compatibility filter. In the UI, Admin or Coordinator clicks **Override** in that patient's Ranking Results row, enters a reason of at least 12 characters, and confirms. The browser calls this endpoint and refreshes the donor ranking; the overridden candidate is moved to the top when it remains eligible. The operation is logged for audit. This is a simulated ranking override, not a clinical allocation decision.

### Example: simulated confirmation

```json
POST /api/allocation/confirm
Content-Type: application/json

{"donor_id":"D-DEMO-001","patient_id":"P-DEMO-001"}
```

The donor and patient must exist and pass the prototype compatibility filter. The endpoint returns a conflict if either already has a simulated confirmed claim.

## Tests

Install dependencies, configure the test database/environment as required by `tests/test_api.py`, then run:

```powershell
pytest -v
```

Run only the scoring tests:

```powershell
pytest -v tests/test_engine.py
```

Run only API tests:

```powershell
pytest -v tests/test_api.py
```

Tests that access MySQL need a reachable test database with the required schema and migrations. Do not point destructive test setup at a database containing important records. The test suite should be run locally before deployment; a successful syntax check is not a substitute for integration tests.

## Security, privacy and limitations

- Use synthetic records only. Do not enter names or details of real patients or donors.
- Passwords are stored as Werkzeug password hashes; passwords are not stored in plain text.
- Keep `.env` and all credentials out of Git and screenshots.
- The coordinator and hospital passwords listed in this README are local demonstration credentials only; replace them before public release or deployment. Administrator credentials are intentionally omitted. The login dropdown does not create accounts or reset passwords; it only verifies that the selected role matches the account's stored role.
- Use HTTPS and a private random `SECRET_KEY` in deployment.
- The matching rules are simplified and not a complete medical compatibility assessment.
- The scoring weights, special indicators, urgent override and simulated confirmation are not clinical policy.
- Straight-line distance does not estimate transport time or organ viability.
- The same-state comparison is an illustrative baseline, not a representation of a real state's allocation policy.
- The application is not certified, validated or approved for clinical use.

## Troubleshooting

| Problem | What to check |
|---|---|
| `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that PowerShell terminal, then activate again. |
| MySQL connection error | Confirm MySQL is running and `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` are correct. |
| Login says database is not ready | Apply `db/migration_users.sql`, then run `python create_admin.py`. |
| Hospital account cannot register patients | Confirm `users.hospital_id` is set to an existing `hospitals.hospital_id`. |
| Hospital sees no patients | Check that those patients have the same `hospital_id` as the logged-in hospital account. |
| Distance score looks approximate | Add valid latitude/longitude for both donor and patient hospitals. |
| Audit or scoring-policy request fails | Apply the corresponding audit/scoring migration to the same database configured in `.env`. |
| Allocation confirmation fails | Confirm the concurrency migration ran and donor/patient IDs exist, are compatible, and have not already been claimed. |
| `Duplicate column` during manual migration | The column already exists; inspect with `DESCRIBE table_name` and do not add it again. |

---

**Project status:** Academic prototype for demonstration and evaluation. Use only synthetic data and clearly label all allocation-related outputs as simulations.
