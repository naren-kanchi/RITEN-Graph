-- Application-owned data. Source facts are immutable to the app, so everyday INSERT/UPDATE/DELETE
-- happens here: analyst annotations and the curated supplier-to-company alias workflow.
CREATE TABLE app_user (
    user_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(40) NOT NULL UNIQUE CHECK (username ~ '^[A-Za-z0-9_.-]{3,40}$'),
    password_hash TEXT NOT NULL CHECK (password_hash LIKE '$argon2%'),
    role TEXT NOT NULL CHECK (role IN ('analyst','admin')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE annotation (
    annotation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('actor','trade_flow','restriction','company')),
    entity_key TEXT NOT NULL CHECK (length(entity_key) BETWEEN 1 AND 40),
    note TEXT NOT NULL CHECK (length(trim(note)) BETWEEN 1 AND 2000),
    created_by INT NOT NULL REFERENCES app_user(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- A label stays unlinked until a person proposes a mapping with evidence and a different
-- administrator approves it. There is deliberately no automatic name matching.
CREATE TABLE supplier_company_alias (
    alias_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_label_id INT NOT NULL REFERENCES supplier_label(supplier_label_id),
    company_key INT NOT NULL REFERENCES company(company_key),
    evidence TEXT NOT NULL CHECK (length(trim(evidence)) >= 10),
    confidence TEXT NOT NULL CHECK (confidence IN ('low','medium','high')),
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','approved','rejected')),
    proposed_by INT NOT NULL REFERENCES app_user(user_id),
    reviewed_by INT REFERENCES app_user(user_id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alias_review_complete CHECK (
        (status = 'proposed' AND reviewed_by IS NULL AND reviewed_at IS NULL)
        OR (status <> 'proposed' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
-- A label may have many proposals but only one approved company.
CREATE UNIQUE INDEX alias_one_approved_uq ON supplier_company_alias (supplier_label_id) WHERE status = 'approved';
CREATE TABLE audit_log (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('INSERT','UPDATE','DELETE')),
    row_pk TEXT NOT NULL,
    old_row JSONB,
    new_row JSONB,
    acting_user_id INT,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
