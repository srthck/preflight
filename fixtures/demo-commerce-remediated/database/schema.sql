-- Demo Commerce — users table (remediated release, pre-migration state)
--
-- Consumers have already stopped reading phone_number (see user-service and
-- profile-api below); the column itself has not been dropped yet. This is
-- the mid-point of a real expand/contract migration: safe to ship the
-- destructive migration.sql now, because nothing downstream depends on the
-- column anymore.

CREATE TABLE users (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    email        TEXT    NOT NULL,
    phone_number TEXT                -- no longer read by any consumer below
);
