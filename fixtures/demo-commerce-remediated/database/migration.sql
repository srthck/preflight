-- Demo Commerce — remediated release migration fixture
--
-- Same destructive statement as the canonical scenario. The difference in
-- this fixture is entirely on the application side (see user-service and
-- profile-api): no consumer reads users.phone_number any more, so this
-- migration's blast radius and rollback truth are expected to come out
-- differently from the canonical (unremediated) fixture even though the
-- SQL itself is byte-for-byte identical.

ALTER TABLE users DROP COLUMN phone_number;
