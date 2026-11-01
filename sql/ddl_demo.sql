-- Disposable DDL demonstration: CREATE, ALTER and DROP in one throwaway schema, so DROP can
-- never touch project data. Run: docker compose exec -T postgres psql -U riten_owner -d riten < sql/ddl_demo.sql
BEGIN;
CREATE SCHEMA ddl_demo;
CREATE TABLE ddl_demo.watchlist (
    watch_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_code VARCHAR(10) NOT NULL REFERENCES public.geopolitical_actor(actor_code),
    priority SMALLINT NOT NULL CHECK (priority BETWEEN 1 AND 3)
);
ALTER TABLE ddl_demo.watchlist ADD COLUMN reason TEXT;
ALTER TABLE ddl_demo.watchlist ALTER COLUMN reason SET DEFAULT 'unspecified';
ALTER TABLE ddl_demo.watchlist ADD CONSTRAINT watchlist_actor_uq UNIQUE (actor_code);
CREATE INDEX watchlist_priority_idx ON ddl_demo.watchlist (priority);
CREATE VIEW ddl_demo.v_high_priority AS SELECT actor_code, reason FROM ddl_demo.watchlist WHERE priority = 1;
INSERT INTO ddl_demo.watchlist (actor_code, priority) VALUES ('US', 1);
SELECT * FROM ddl_demo.v_high_priority;
DROP VIEW ddl_demo.v_high_priority;
DROP INDEX ddl_demo.watchlist_priority_idx;
ALTER TABLE ddl_demo.watchlist DROP COLUMN reason;
DROP TABLE ddl_demo.watchlist;
DROP SCHEMA ddl_demo;
COMMIT;
