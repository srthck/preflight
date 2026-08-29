-- Demo Commerce — safe migration fixture
--
-- Used by the "demo-commerce-phone-verified-addition" scenario to prove
-- PreFlight does not manufacture danger: an additive column has no
-- destructive schema finding and no rollback-safety violation, because
-- the real analyzers never report evidence they cannot find.

ALTER TABLE users ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;
