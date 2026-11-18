-- Run once against the existing organ_allocation database.
USE `organ_allocation`;

CREATE TABLE IF NOT EXISTS `scoring_policy` (
    `policy_id` TINYINT NOT NULL PRIMARY KEY,
    `urgency_weight` DECIMAL(5,4) NOT NULL DEFAULT 0.4000,
    `match_weight` DECIMAL(5,4) NOT NULL DEFAULT 0.3000,
    `wait_weight` DECIMAL(5,4) NOT NULL DEFAULT 0.2000,
    `distance_weight` DECIMAL(5,4) NOT NULL DEFAULT 0.1000,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `chk_policy_weights_sum` CHECK (ABS(urgency_weight + match_weight + wait_weight + distance_weight - 1.0) < 0.0001)
) ENGINE=InnoDB;

INSERT IGNORE INTO `scoring_policy` (policy_id) VALUES (1);
