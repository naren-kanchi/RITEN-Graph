-- Each index exists for a named query; EXPLAIN evidence is in docs/QUERIES.md.
-- Trade explorer: filter by period, or by a directed country pair and period.
CREATE INDEX trade_period_idx ON trade_flow (year, quarter);
CREATE INDEX trade_pair_year_idx ON trade_flow (exporter_actor_code, importer_actor_code, year);
CREATE INDEX trade_importer_year_idx ON trade_flow (importer_actor_code, year);
CREATE INDEX trade_hardware_year_idx ON trade_flow (hardware_type, year);
CREATE INDEX trade_supplier_idx ON trade_flow (supplier_label_id);
-- Partial: only 94 of 5,656 rows carry a control, and the restricted-trade report reads only those.
CREATE INDEX trade_controlled_idx ON trade_flow (year, exporter_actor_code) WHERE export_control_applied;
-- Restriction explorer and target reports.
CREATE INDEX restriction_target_date_idx ON restriction_measure (target_actor_code, date_implemented);
CREATE INDEX restriction_imposer_date_idx ON restriction_measure (imposing_actor_code, date_implemented);
CREATE INDEX restriction_search_idx ON restriction_measure USING GIN (search_vector);
-- Foreign keys without a covering index.
CREATE INDEX company_hq_idx ON company (hq_actor_code);
CREATE INDEX annotation_entity_idx ON annotation (entity_type, entity_key);
CREATE INDEX alias_status_idx ON supplier_company_alias (status, supplier_label_id);
CREATE INDEX audit_logged_idx ON audit_log (logged_at DESC);
