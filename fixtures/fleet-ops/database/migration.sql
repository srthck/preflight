-- Fleet Ops — two independent destructive changes in one migration.
--
-- Each statement is a separate, independently-analyzable change:
--   drivers.license_number  is read by DispatchService
--   drivers.medical_cert    is read by AuditService
--
-- Both services call ComplianceAPI, so these two structurally independent
-- changes converge on one downstream entity. A pipeline that collapses a
-- migration into a single "primary" change cannot see that convergence.

ALTER TABLE drivers DROP COLUMN license_number;
ALTER TABLE drivers DROP COLUMN medical_cert;
