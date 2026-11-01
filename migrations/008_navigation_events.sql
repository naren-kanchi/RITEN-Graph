-- Anonymous navigation events feed the prefetch worker. No user id is stored: session_id is a
-- random browser value, so this table holds no personally identifying data.
CREATE TABLE navigation_event (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    view_type TEXT NOT NULL CHECK (view_type IN ('actor_profile','graph_neighborhood')),
    entity_key VARCHAR(40) NOT NULL,
    client_event_id VARCHAR(64),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX navigation_session_idx ON navigation_event (session_id, occurred_at, event_id);
-- Replaying the same event from a client must not count twice.
CREATE UNIQUE INDEX navigation_replay_uq ON navigation_event (session_id, client_event_id) WHERE client_event_id IS NOT NULL;

-- One row per prefetched cache entry: the evidence for the usefulness and waste metrics.
CREATE TABLE prefetch_stat (
    prefetch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cache_key TEXT NOT NULL,
    prefetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_bytes INT NOT NULL CHECK (payload_bytes >= 0),
    used_at TIMESTAMPTZ
);
CREATE INDEX prefetch_key_idx ON prefetch_stat (cache_key, prefetched_at DESC);
