USE organ_allocation;

-- MySQL-compatible, repeatable migration. This avoids the unsupported
-- ALTER TABLE ... ADD COLUMN IF NOT EXISTS syntax on older MySQL releases.
DROP PROCEDURE IF EXISTS migrate_distance_concurrency_roles;
DELIMITER $$
CREATE PROCEDURE migrate_distance_concurrency_roles()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'hospital_id'
    ) THEN
        ALTER TABLE users ADD COLUMN hospital_id VARCHAR(50) NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hospitals' AND COLUMN_NAME = 'latitude'
    ) THEN
        ALTER TABLE hospitals ADD COLUMN latitude DECIMAL(10,7) NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hospitals' AND COLUMN_NAME = 'longitude'
    ) THEN
        ALTER TABLE hospitals ADD COLUMN longitude DECIMAL(10,7) NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'users'
          AND CONSTRAINT_NAME = 'fk_users_hospital'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT fk_users_hospital
            FOREIGN KEY (hospital_id) REFERENCES hospitals(hospital_id) ON DELETE SET NULL;
    END IF;
END$$
DELIMITER ;

CALL migrate_distance_concurrency_roles();
DROP PROCEDURE migrate_distance_concurrency_roles;

-- One-to-one simulated claims: unique donor and patient prevent duplicate claims.
CREATE TABLE IF NOT EXISTS allocations (
    allocation_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    donor_id VARCHAR(50) NOT NULL,
    patient_id VARCHAR(50) NOT NULL,
    confirmed_by VARCHAR(80) NOT NULL,
    status ENUM('SIMULATED_CONFIRMED','CANCELLED') NOT NULL DEFAULT 'SIMULATED_CONFIRMED',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_allocation_donor (donor_id),
    UNIQUE KEY uq_allocation_patient (patient_id),
    CONSTRAINT fk_allocation_donor FOREIGN KEY (donor_id) REFERENCES donors(donor_id),
    CONSTRAINT fk_allocation_patient FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
) ENGINE=InnoDB;
