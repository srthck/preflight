-- Demo Commerce — users table
-- This schema is an analysis fixture, not a production database definition.
--
-- Dependency significance
-- -----------------------
-- The `phone_number` column (line 6 below) is the canonical "changed entity"
-- for Day 1 PreFlight analysis. A change to this column propagates through:
--
--   users.phone_number
--     --DB_READ-->  UserService
--     --HTTP_CALL-> ProfileAPI
--     --API_CONSUMES-> AndroidClient
--
-- See fixtures/demo-commerce/README.md for the full dependency map.

CREATE TABLE users (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    email        TEXT    NOT NULL,
    phone_number TEXT                -- nullable: not all users provide a phone
);
