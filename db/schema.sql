-- Unified Organ Allocation System Database Schema
-- MySQL 8.0, InnoDB Engine

CREATE DATABASE IF NOT EXISTS `organ_allocation`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `organ_allocation`;

-- 1. States table
CREATE TABLE IF NOT EXISTS `states` (
    `state_id` INT AUTO_INCREMENT PRIMARY KEY,
    `state_name` VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB;

-- 2. Hospitals table
CREATE TABLE IF NOT EXISTS `hospitals` (
    `hospital_id` VARCHAR(50) PRIMARY KEY,
    `hospital_name` VARCHAR(255) NOT NULL,
    `state_id` INT NOT NULL,
    `hospital_type` ENUM('Government', 'Private') NOT NULL,
    CONSTRAINT `fk_hospitals_state` FOREIGN KEY (`state_id`) REFERENCES `states` (`state_id`)
) ENGINE=InnoDB;

-- 3. Patients table
CREATE TABLE IF NOT EXISTS `patients` (
    `patient_id` VARCHAR(50) PRIMARY KEY,
    `name` VARCHAR(255) NOT NULL,
    `age` INT NOT NULL,
    `gender` ENUM('Male', 'Female', 'Other') NOT NULL,
    `state` VARCHAR(100) NOT NULL,
    `hospital_id` VARCHAR(50) NOT NULL,
    `hospital_type` ENUM('Government', 'Private') NOT NULL,
    `blood_group` ENUM('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-') NOT NULL,
    `organ_needed` ENUM('Kidney', 'Liver', 'Heart', 'Lung') NOT NULL,
    `hla_type` VARCHAR(255) NOT NULL,
    `dialysis_status` ENUM('Yes', 'No') NOT NULL,
    `icu_level` ENUM('Not Admitted', 'Standard', 'ICU', 'Critical') NOT NULL,
    `organ_failure_stage` INT NOT NULL,
    `days_on_waitlist` INT NOT NULL,
    `family_donor_relative` ENUM('Yes', 'No') NOT NULL,
    `registered_date` DATE NOT NULL,
    CONSTRAINT `fk_patients_hospital` FOREIGN KEY (`hospital_id`) REFERENCES `hospitals` (`hospital_id`)
) ENGINE=InnoDB;

-- 4. Donors table
CREATE TABLE IF NOT EXISTS `donors` (
    `donor_id` VARCHAR(50) PRIMARY KEY,
    `state` VARCHAR(100) NOT NULL,
    `hospital_id` VARCHAR(50) NOT NULL,
    `blood_group` ENUM('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-') NOT NULL,
    `organ_type` ENUM('Kidney', 'Liver', 'Heart', 'Lung') NOT NULL,
    `hla_type` VARCHAR(255) NOT NULL,
    `logged_datetime` DATETIME NOT NULL,
    `viability_hours` INT NOT NULL,
    CONSTRAINT `fk_donors_hospital` FOREIGN KEY (`hospital_id`) REFERENCES `hospitals` (`hospital_id`)
) ENGINE=InnoDB;

-- 5. Scores table
CREATE TABLE IF NOT EXISTS `scores` (
    `score_id` INT AUTO_INCREMENT PRIMARY KEY,
    `patient_id` VARCHAR(50) NOT NULL,
    `donor_id` VARCHAR(50) NOT NULL,
    `urgency_score` DECIMAL(5,2) NOT NULL,
    `match_score` DECIMAL(5,2) NOT NULL,
    `wait_score` DECIMAL(5,2) NOT NULL,
    `distance_score` DECIMAL(5,2) NOT NULL,
    `total_score` DECIMAL(5,2) NOT NULL,
    `computed_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT `unique_patient_donor_score` UNIQUE (`patient_id`, `donor_id`),
    CONSTRAINT `fk_scores_patient` FOREIGN KEY (`patient_id`) REFERENCES `patients` (`patient_id`) ON DELETE CASCADE,
    CONSTRAINT `fk_scores_donor` FOREIGN KEY (`donor_id`) REFERENCES `donors` (`donor_id`) ON DELETE CASCADE
) ENGINE=InnoDB;


-- 6. Audit log table (records prototype actions; no real patient data)
CREATE TABLE IF NOT EXISTS `audit_logs` (
    `audit_id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `event_type` VARCHAR(50) NOT NULL,
    `entity_id` VARCHAR(50) NOT NULL,
    `details_json` JSON NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_audit_entity` (`entity_id`),
    INDEX `idx_audit_created` (`created_at`)
) ENGINE=InnoDB;
