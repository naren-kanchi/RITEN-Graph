-- ALTER in real use. These rules were found while auditing the data after the base schema was
-- written, so they arrive as a later migration: the natural grain of a trade observation, and
-- the full-text column for searching restriction descriptions.
ALTER TABLE trade_flow
    ADD CONSTRAINT trade_flow_grain_uq UNIQUE (year, quarter, exporter_actor_code, importer_actor_code, hardware_type);

ALTER TABLE restriction_measure
    ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            description || ' ' || replace(affected_technology, '_', ' ') || ' ' ||
            replace(restriction_type, '_', ' ') || ' ' || source_reference)
    ) STORED;

ALTER TABLE import_batch ADD COLUMN data_version TEXT;
