-- Demo Commerce — canonical migration fixture
--
-- This is the migration PreFlight analyzes for the
-- "demo-commerce-phone-number-removal" scenario. It is real input: the
-- DeploymentAnalyzer parses this file with SQLGlot and produces the
-- DROP_COLUMN finding from it. Nothing about the finding is hand-coded
-- in the orchestrator — remove this statement (see migration_safe.sql
-- for a non-destructive alternative) and the finding disappears.

ALTER TABLE users DROP COLUMN phone_number;
