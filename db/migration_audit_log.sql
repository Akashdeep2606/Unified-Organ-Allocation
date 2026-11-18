-- Run once against the existing organ_allocation database.
USE `organ_allocation`;

CREATE TABLE IF NOT EXISTS `audit_logs` (
    `audit_id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `event_type` VARCHAR(50) NOT NULL,
    `entity_id` VARCHAR(50) NOT NULL,
    `details_json` JSON NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_audit_entity` (`entity_id`),
    INDEX `idx_audit_created` (`created_at`)
) ENGINE=InnoDB;
