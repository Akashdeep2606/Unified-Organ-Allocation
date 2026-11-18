-- Run once in MySQL Workbench against organ_allocation.
USE organ_allocation;

CREATE TABLE IF NOT EXISTS urgent_overrides (
    override_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    donor_id VARCHAR(50) NOT NULL,
    patient_id VARCHAR(50) NOT NULL,
    reason TEXT NOT NULL,
    approved_by VARCHAR(80) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_urgent_override_donor_created (donor_id, created_at),
    CONSTRAINT fk_override_donor FOREIGN KEY (donor_id) REFERENCES donors(donor_id) ON DELETE CASCADE,
    CONSTRAINT fk_override_patient FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
) ENGINE=InnoDB;
