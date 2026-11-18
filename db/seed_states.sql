-- Seed initial states into the states table
USE `organ_allocation`;

INSERT INTO `states` (`state_name`)
VALUES
    ('Punjab'),
    ('Maharashtra'),
    ('Tamil Nadu'),
    ('Kerala')
ON DUPLICATE KEY UPDATE `state_name` = VALUES(`state_name`);
