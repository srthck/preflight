-- Fleet Ops — driver compliance schema fixture.
--
-- This fixture exists to prove CONVERGENCE: two structurally independent
-- schema changes (license_number and medical_cert) are each read by a
-- different service, and both of those services call the same downstream
-- compliance API. A change to either column alone reaches ComplianceAPI;
-- changing both means two independent causes converge on one entity.
--
-- Deliberately unrelated to the demo-commerce fixture in domain, table
-- names, column names, service names, and language mix.

CREATE TABLE drivers (
    id             INTEGER PRIMARY KEY,
    full_name      TEXT    NOT NULL,
    depot_code     TEXT    NOT NULL,
    license_number TEXT,           -- read by DispatchService
    medical_cert   TEXT            -- read by AuditService
);
