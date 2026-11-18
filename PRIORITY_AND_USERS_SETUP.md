# User accounts and priority-rule update

## Create coordinator and hospital accounts

1. Log in as the administrator.
2. Use the authenticated API endpoint `POST /api/users`.
3. JSON body example:

```json
{"username":"coordinator1","password":"Choose-A-Strong-Password","role":"coordinator"}
```

For a hospital account, use `"role":"hospital"`. Only an admin can create accounts. Passwords are stored as password hashes. `GET /api/users` lists accounts (without password hashes).

The endpoint uses the browser's authenticated session cookie. The easiest way to call it during development is the browser developer console while logged in:

```javascript
fetch('/api/users', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({username:'coordinator1', password:'Choose-A-Strong-Password', role:'coordinator'})
}).then(r => r.json()).then(console.log);
```

## Priority indicators

Ranking results now include `special_priority` flags for same-hospital and recorded family-donor-relative information. They are informational only; they do not change clinical eligibility or automatically boost a candidate. This avoids asserting an unvalidated medical/legal policy.

## Coordinator urgent override

Run `db/migration_priority_rules.sql` once in MySQL Workbench. Then, while logged in as admin or coordinator, call `POST /api/allocation/urgent-override` with:

```json
{"donor_id":"D100","patient_id":"P100","reason":"Documented synthetic scenario requiring coordinator review."}
```

The endpoint rejects a patient who fails the existing exact organ and blood-group compatibility filters. The latest valid override is moved to the top on the next ranking request and is labelled with `urgent_override`, reason and approver in the API result. This is a simulation only, not a clinical allocation decision.

## Important

The hospital role is currently an authenticated role. Fine-grained hospital-to-own-record restrictions are not implemented yet; do not use this prototype with real patient data. Urgent override requires a documented reason and coordinator/admin role. Real-world deployment requires formally approved allocation policy, audit review, concurrency-safe allocation confirmation, privacy controls and clinical/legal validation.
