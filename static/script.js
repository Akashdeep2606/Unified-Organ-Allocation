/**
 * Vanilla JavaScript controller for Unified Organ Allocation Prototype.
 */

const originalFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401 && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
    }
    return response;
};

document.addEventListener("DOMContentLoaded", async () => {
    try {
        const meResponse = await fetch("/api/auth/me");
        const me = await meResponse.json();
        if (meResponse.ok) {
            document.getElementById("signed-in-user").textContent = `${me.username} · ${me.role}${me.hospital_id ? ` · ${me.hospital_id}` : ""}`;
            const role = me.role;
            const donorCard = document.getElementById("donor-form")?.closest(".card");
            const patientCard = document.getElementById("patient-form")?.closest(".card");
            const overview = document.getElementById("overview-title")?.closest("section");
            const weights = document.getElementById("weights-form")?.closest(".border.rounded.p-3");
            const auditHeading = [...document.querySelectorAll("h3")].find(h => h.textContent.includes("Recent audit events"));
            const auditTable = auditHeading?.parentElement;
            if (role === "hospital") {
                if (donorCard) donorCard.classList.add("d-none");
                if (overview) overview.classList.add("d-none");
                document.getElementById("p_hospital") && (document.getElementById("p_hospital").value = me.hospital_id || "");
                document.getElementById("p_hospital")?.setAttribute("readonly", "readonly");
                document.getElementById("p_state")?.setAttribute("disabled", "disabled");
                const patientHeading = patientCard?.querySelector(".card-header h2, .card-header h3");
                if (patientHeading) patientHeading.textContent = "My Hospital – Patient Management";
            } else if (role === "coordinator") {
                if (weights) weights.classList.add("d-none");
            }
            if (role !== "admin" && role !== "coordinator" && auditTable) auditTable.classList.add("d-none");
        }
    } catch (_) { /* API requests below will redirect if the session has expired. */ }
    document.getElementById("logout-button")?.addEventListener("click", async () => {
        await fetch("/api/auth/logout", {method: "POST"});
        window.location.href = "/login";
    });
    const donorForm = document.getElementById("donor-form");
    const submitBtn = document.getElementById("submit-btn");
    const statusDiv = document.getElementById("status-message");
    const calloutDiv = document.getElementById("allocation-callout");
    const tableBody = document.getElementById("results-table-body");
    const countBadge = document.getElementById("results-count");
    let latestDonorId = "";

    // Sample presets for quick one-click testing
    const presets = {
        1: {
            organ: "Kidney",
            blood: "O+",
            state: "Maharashtra",
            hospital: "H008",
            hla: "A3,A24,B7,B60,DR13,DR15",
            viability: 36,
        },
        2: {
            organ: "Liver",
            blood: "B+",
            state: "Kerala",
            hospital: "H017",
            hla: "A2,A33,B14,B51,DR1,DR7",
            viability: 24,
        },
        3: {
            organ: "Kidney",
            blood: "A+",
            state: "Tamil Nadu",
            hospital: "H012",
            hla: "A2,A24,B7,B44,DR4,DR7",
            viability: 30,
        },
    };

    function applyPreset(presetNumber) {
        const p = presets[presetNumber];
        if (!p) return;
        document.getElementById("organ_type").value = p.organ;
        document.getElementById("blood_group").value = p.blood;
        document.getElementById("state").value = p.state;
        document.getElementById("hospital_id").value = p.hospital;
        document.getElementById("hla_type").value = p.hla;
        document.getElementById("viability_hours").value = p.viability;
        generateNewDonorId();
    }

    function generateNewDonorId() {
        const donorIdInput = document.getElementById("donor_id");
        donorIdInput.value = "D" + Math.floor(100 + Math.random() * 900);
    }

    // Set initial donor ID
    generateNewDonorId();

    // Event listeners for sample presets
    document.getElementById("preset-1-btn")?.addEventListener("click", () => applyPreset(1));
    document.getElementById("preset-2-btn")?.addEventListener("click", () => applyPreset(2));
    document.getElementById("preset-3-btn")?.addEventListener("click", () => applyPreset(3));

    donorForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        // Clear previous alert & callout
        statusDiv.className = "d-none";
        statusDiv.textContent = "";
        calloutDiv.className = "d-none";
        calloutDiv.innerHTML = "";

        const payload = {
            donor_id: document.getElementById("donor_id").value.trim(),
            organ_type: document.getElementById("organ_type").value,
            blood_group: document.getElementById("blood_group").value,
            state: document.getElementById("state").value,
            hospital_id: document.getElementById("hospital_id").value.trim(),
            hla_type: document.getElementById("hla_type").value.trim(),
            viability_hours: parseInt(document.getElementById("viability_hours").value, 10),
            logged_datetime: new Date().toISOString().replace("T", " ").substring(0, 19),
        };

        if (!payload.organ_type || !payload.blood_group || !payload.state) {
            showAlert("Please select Organ Type, Blood Group, and State.", "warning");
            return;
        }

        latestDonorId = payload.donor_id;
        submitBtn.disabled = true;
        submitBtn.innerHTML = `
            <span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>
            Ranking Patients...
        `;

        try {
            const response = await fetch("/api/donor", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (!response.ok) {
                const errMsg = data.error || "Failed to log donor and generate ranking.";
                showAlert(errMsg, "danger");
                return;
            }

            renderRankingTable(data, payload);
            refreshOverview();
            showAlert(`Evaluated ${data.length} compatible candidates for Donor ${payload.donor_id} (${payload.blood_group} ${payload.organ_type}).`, "success");

        } catch (error) {
            showAlert(`Network or server connection error: ${error.message}`, "danger");
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = "Log Donor & Rank Patients";
        }
    });

    function showAlert(message, level) {
        statusDiv.className = `alert alert-${level} mb-3 py-2 px-3 small`;
        statusDiv.textContent = message;
    }

    function renderRankingTable(candidates, donorPayload) {
        tableBody.innerHTML = "";
        countBadge.textContent = `${candidates.length} candidates`;

        if (candidates.length === 0) {
            calloutDiv.className = "d-none";
            tableBody.innerHTML = `
                <tr>
                    <td colspan="10" class="text-center text-muted py-5">
                        <div class="mb-2 text-warning">
                            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <circle cx="12" cy="12" r="10"/>
                                <line x1="12" y1="8" x2="12" y2="12"/>
                                <line x1="12" y1="16" x2="12.01" y2="16"/>
                            </svg>
                        </div>
                        <div class="fw-semibold text-dark">No Compatible Candidates Found</div>
                        <small class="text-muted">No waitlist patients match ${donorPayload.blood_group} ${donorPayload.organ_type}.</small>
                    </td>
                </tr>
            `;
            return;
        }

        // 1. Render Allocation Callout for Rank 1
        const primary = candidates[0];
        const isTieAtRank1 = primary.escalate_to_coordinator;

        let calloutHtml = "";
        if (isTieAtRank1) {
            calloutHtml = `
                <div class="alert alert-warning border-warning d-flex align-items-start gap-3 mb-4 p-3 shadow-sm">
                    <div class="text-warning-emphasis pt-1">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    </div>
                    <div>
                        <h6 class="alert-heading fw-bold mb-1">Review Required: Tie Detected at Rank 1 — Coordinator Escalation Required</h6>
                        <p class="small mb-1">
                            Candidate <strong class="mono">${escapeHtml(primary.patient_id)}</strong> (${escapeHtml(primary.name)}) and another candidate share identical scores and tiebreaker attributes. 
                            Manual clinical coordinator review is required before confirming the single organ allocation.
                        </p>
                    </div>
                </div>
            `;
        } else {
            calloutHtml = `
                <div class="card border-success bg-white mb-4 shadow-sm">
                    <div class="card-body p-3">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <div class="d-flex align-items-center gap-2">
                                <span class="badge bg-success text-white px-2 py-1">Primary Match (Rank 1)</span>
                                <span class="text-muted small">Single Organ: <strong>${escapeHtml(donorPayload.organ_type)}</strong> (${escapeHtml(donorPayload.blood_group)})</span>
                            </div>
                            <span class="badge bg-success-subtle text-success-emphasis border border-success-subtle mono">Total Score: ${Number(primary.total_score).toFixed(2)}</span>
                        </div>
                        <div class="row g-2 align-items-center">
                            <div class="col-md-4">
                                <span class="text-muted small d-block">Primary Match</span>
                                <strong class="text-dark fs-6">${escapeHtml(primary.name)}</strong>
                                <span class="mono text-muted small ms-1">(${escapeHtml(primary.patient_id)})</span>
                            </div>
                            <div class="col-md-3">
                                <span class="text-muted small d-block">Location &amp; Hospital</span>
                                <span>${escapeHtml(primary.state)} • ${escapeHtml(primary.hospital_id)}</span>
                            </div>
                            <div class="col-md-2">
                                <span class="text-muted small d-block">Waitlist Days</span>
                                <span class="fw-semibold">${primary.days_on_waitlist} days</span>
                            </div>
                            <div class="col-md-3 text-md-end">
                                <small class="text-muted d-block">Standby Candidates</small>
                                <span class="text-secondary small fw-medium">${candidates.length - 1} standby backups queued</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }
        calloutHtml += `<div class="alert alert-info py-2 small mb-3">Recommendation only: no organ is allocated or reserved by this prototype. Final allocation requires authorised medical/coordinator confirmation.</div>`;
        calloutDiv.innerHTML = calloutHtml;
        calloutDiv.className = "d-block";

        // 2. Render Table Rows
        candidates.forEach((patient, index) => {
            const row = document.createElement("tr");
            const rank = index + 1;
            const isRank1 = rank === 1;

            if (isRank1) {
                row.className = "top-match-row table-success";
            }

            const patientId = escapeHtml(patient.patient_id || "");
            const name = escapeHtml(patient.name || "");
            const totalScore = Number(patient.total_score || 0).toFixed(2);
            const urgencyScore = Number(patient.urgency_score || 0).toFixed(2);
            const matchScore = Number(patient.match_score || 0).toFixed(2);
            const waitScore = Number(patient.wait_score || 0).toFixed(2);
            const distanceScore = Number(patient.distance_score || 0).toFixed(2);
            const distanceKm = patient.distance_km !== null && patient.distance_km !== undefined
                ? `${Number(patient.distance_km).toFixed(2)} km`
                : "N/A (coordinates unavailable)";
            const waitDays = patient.days_on_waitlist !== undefined ? patient.days_on_waitlist : "N/A";

            // Determine accurate, non-confusing allocation status
            let statusBadge = "";
            if (isRank1) {
                if (patient.escalate_to_coordinator) {
                    statusBadge = `<span class="badge bg-warning text-dark border border-warning-subtle">Review (Rank 1 Tie)</span>`;
                } else {
                    statusBadge = `<span class="badge bg-success text-white">Primary Match (Rank 1)</span>`;
                }
            } else {
                if (patient.escalate_to_coordinator) {
                    statusBadge = `<span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle">Standby (Tied)</span>`;
                } else {
                    statusBadge = `<span class="badge bg-light text-secondary border">Standby (Backup #${rank - 1})</span>`;
                }
            }

            row.innerHTML = `
                <th scope="row" class="text-center mono ${isRank1 ? 'fw-bold text-success' : 'text-muted'}">${rank}</th>
                <td class="mono fw-medium">${patientId}</td>
                <td>
                    <div class="fw-semibold text-dark">${name}</div>
                    <small class="text-muted">${escapeHtml(patient.state || '')} • Age: ${patient.age || 'N/A'}</small>
                </td>
                <td class="text-center mono fw-bold ${isRank1 ? 'text-success' : 'text-primary'} fs-6">${totalScore}</td>
                <td class="text-center mono small">${urgencyScore}</td>
                <td class="text-center mono small">${matchScore}</td>
                <td class="text-center mono small">${waitScore}</td>
                <td class="text-center mono small">${distanceScore}</td>
                <td class="text-center mono small">${distanceKm}</td>
                <td class="text-center small">${waitDays}d</td>
                <td>${statusBadge}</td>
            `;

            tableBody.appendChild(row);
        });
    }

    const patientForm = document.getElementById("patient-form");
    patientForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const status = document.getElementById("patient-status");
        const payload = {
            patient_id: document.getElementById("p_patient_id").value.trim(),
            name: document.getElementById("p_name").value.trim(),
            age: Number(document.getElementById("p_age").value),
            gender: document.getElementById("p_gender").value,
            state: document.getElementById("p_state").value,
            hospital_id: document.getElementById("p_hospital").value.trim(),
            hospital_type: document.getElementById("p_hospital_type").value,
            blood_group: document.getElementById("p_blood").value,
            organ_needed: document.getElementById("p_organ").value,
            hla_type: document.getElementById("p_hla").value.trim(),
            dialysis_status: document.getElementById("p_dialysis").value,
            icu_level: document.getElementById("p_icu").value,
            organ_failure_stage: Number(document.getElementById("p_stage").value),
            days_on_waitlist: Number(document.getElementById("p_wait").value),
            family_donor_relative: document.getElementById("p_relative").value
        };
        const button = document.getElementById("patient-submit");
        button.disabled = true;
        try {
            const response = await fetch("/api/patients", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Patient registration failed.");
            status.className = "small mt-2 text-success";
            status.textContent = result.message + " Re-run donor ranking to include this patient.";
            patientForm.reset();
            refreshOverview();
            refreshPatients();
        } catch (error) {
            status.className = "small mt-2 text-danger";
            status.textContent = error.message;
        } finally {
            button.disabled = false;
        }
    });

    async function refreshPatients() {
        const body = document.getElementById("patients-list-body");
        if (!body) return;
        try {
            const response = await fetch("/api/patients");
            const patients = await response.json();
            if (!response.ok) throw new Error(patients.error || "Could not load patients.");
            body.innerHTML = patients.length ? patients.map(patient => `<tr><td class="mono">${escapeHtml(patient.patient_id)}</td><td>${escapeHtml(patient.name)}</td><td>${escapeHtml(patient.organ_needed)}</td><td>${escapeHtml(patient.blood_group)}</td><td>${escapeHtml(patient.state)}</td><td>${escapeHtml(patient.days_on_waitlist)}</td><td><button class="btn btn-sm btn-outline-danger" data-delete-patient="${escapeHtml(patient.patient_id)}" type="button">Delete</button></td></tr>`).join("") : '<tr><td colspan="7" class="text-muted">No patients registered.</td></tr>';
        } catch (error) {
            body.innerHTML = `<tr><td colspan="7" class="text-danger">${escapeHtml(error.message)}</td></tr>`;
        }
    }

    document.getElementById("refresh-patients")?.addEventListener("click", refreshPatients);
    document.getElementById("patients-list-body")?.addEventListener("click", async event => {
        const button = event.target.closest("[data-delete-patient]");
        if (!button) return;
        const patientId = button.getAttribute("data-delete-patient");
        if (!window.confirm(`Delete synthetic patient ${patientId}? This also removes linked score records.`)) return;
        button.disabled = true;
        try {
            const response = await fetch(`/api/patients/${encodeURIComponent(patientId)}`, {method: "DELETE"});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Delete failed.");
            refreshPatients();
            refreshOverview();
        } catch (error) { window.alert(error.message); button.disabled = false; }
    });

    async function refreshOverview() {
        const metricIds = {patients: "metric-patients", donors: "metric-donors", score_records: "metric-scores", audit_events: "metric-audit"};
        try {
            const [summaryResponse, auditResponse] = await Promise.all([fetch("/api/dashboard/summary"), fetch("/api/audit-logs?limit=12")]);
            const summary = await summaryResponse.json();
            const audit = await auditResponse.json();
            if (!summaryResponse.ok) throw new Error(summary.error || "Dashboard unavailable");
            Object.entries(metricIds).forEach(([key, id]) => { document.getElementById(id).textContent = summary[key] ?? 0; });
            const body = document.getElementById("audit-table-body");
            if (!auditResponse.ok) throw new Error(audit.error || "Audit log unavailable");
            body.innerHTML = audit.length ? audit.map(item => `<tr><td class="small">${escapeHtml(item.created_at || "")}</td><td>${escapeHtml(item.event_type || "")}</td><td class="mono">${escapeHtml(item.entity_id || "")}</td><td class="small">${escapeHtml(JSON.stringify(item.details_json || {}))}</td></tr>`).join("") : '<tr><td colspan="4" class="text-muted">No audit events recorded yet.</td></tr>';
        } catch (error) {
            document.getElementById("audit-table-body").innerHTML = `<tr><td colspan="4" class="text-danger">${escapeHtml(error.message)}</td></tr>`;
        }
    }

    const weightsForm = document.getElementById("weights-form");
    const weightFields = {urgency: "weight-urgency", match: "weight-match", wait: "weight-wait", distance: "weight-distance"};
    async function loadWeights() {
        const response = await fetch("/api/scoring-weights");
        const weights = await response.json();
        if (!response.ok) throw new Error(weights.error || "Could not load scoring weights.");
        Object.entries(weightFields).forEach(([key, id]) => { document.getElementById(id).value = Math.round(Number(weights[key]) * 100); });
    }
    weightsForm?.addEventListener("submit", async event => {
        event.preventDefault();
        const status = document.getElementById("weights-status");
        const weights = Object.fromEntries(Object.entries(weightFields).map(([key, id]) => [key, Number(document.getElementById(id).value)]));
        if (Object.values(weights).some(value => !Number.isFinite(value)) || Math.abs(Object.values(weights).reduce((a, b) => a + b, 0) - 100) > 0.001) {
            status.className = "small mt-2 text-danger";
            status.textContent = "The four weights must total exactly 100%.";
            return;
        }
        try {
            const response = await fetch("/api/scoring-weights", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(weights)});
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Could not save weights.");
            status.className = "small mt-2 text-success";
            status.textContent = result.message;
            refreshOverview();
        } catch (error) { status.className = "small mt-2 text-danger"; status.textContent = error.message; }
    });
    loadWeights().catch(error => { document.getElementById("weights-status").textContent = error.message; });

    document.getElementById("refresh-overview")?.addEventListener("click", refreshOverview);
    document.getElementById("compare-rankings")?.addEventListener("click", async () => {
        const output = document.getElementById("comparison-result");
        const donorId = latestDonorId || document.getElementById("donor_id").value.trim();
        if (!donorId) { output.textContent = "Enter and evaluate a donor first."; return; }
        output.textContent = "Comparing rankings…";
        try {
            const response = await fetch(`/api/comparison/${encodeURIComponent(donorId)}`);
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || "Comparison failed.");
            output.innerHTML = `<div class="alert alert-info py-2 mb-2"><strong>${escapeHtml(result.baseline_name)}</strong><br>National candidates: ${result.national_candidate_count} · Same-state candidates: ${result.state_only_candidate_count}<br>Common candidates with changed rank: ${result.common_candidates_with_changed_rank}/${result.common_candidates_compared} (${result.rank_change_rate_percent}%)<br><span class="small">${escapeHtml(result.method_note)}</span></div>`;
        } catch (error) { output.textContent = error.message; }
    });

    refreshOverview();
    refreshPatients();

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
});
