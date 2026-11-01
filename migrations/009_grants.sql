-- Least privilege. The API connects as the app role, which can read source facts but has no
-- way to change them, and cannot run DDL. Passwords stay out of this file: the migrator creates
-- the role from the APP_DB_PASSWORD environment variable before this runs.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"app_role";
GRANT INSERT, UPDATE, DELETE ON annotation, supplier_company_alias TO :"app_role";
GRANT INSERT, UPDATE ON app_user TO :"app_role";
GRANT INSERT ON navigation_event TO :"app_role";
GRANT INSERT, UPDATE ON prefetch_stat TO :"app_role";
