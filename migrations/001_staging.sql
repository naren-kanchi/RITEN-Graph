-- Raw staging layer: one table per CSV, exact source column names, everything TEXT.
-- Nothing is cleaned here, so normalization can never silently lose a source string.
CREATE SCHEMA raw;

CREATE TABLE import_batch (
    batch_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','succeeded','failed')),
    row_counts   JSONB NOT NULL DEFAULT '{}'::jsonb,
    triggered_by TEXT NOT NULL DEFAULT 'cli'
);

CREATE TABLE etl_issue (
    issue_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id     BIGINT NOT NULL REFERENCES import_batch(batch_id) ON DELETE CASCADE,
    severity     TEXT NOT NULL CHECK (severity IN ('error','caveat')),
    rule         TEXT NOT NULL,
    source_file  TEXT NOT NULL,
    source_id    TEXT,
    detail       TEXT NOT NULL
);
CREATE INDEX etl_issue_batch_idx ON etl_issue (batch_id, severity, rule);

CREATE TABLE raw.trade_flows (
    trade_id TEXT, year TEXT, quarter TEXT, year_quarter TEXT,
    exporter_country_code TEXT, exporter_country TEXT, exporter_region TEXT,
    importer_country_code TEXT, importer_country TEXT, importer_region TEXT,
    hardware_type TEXT, hardware_category TEXT, volume_units TEXT, trade_value_usd_millions TEXT,
    primary_supplier TEXT, trade_route TEXT, export_control_applied TEXT, restriction_factor TEXT,
    geopolitical_sensitivity TEXT, geo_risk_score_exporter TEXT, geo_risk_score_importer TEXT,
    data_source TEXT, is_synthetic TEXT,
    _batch_id BIGINT NOT NULL REFERENCES import_batch(batch_id), _source_file TEXT NOT NULL, _row_number INT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE raw.sanctions (
    sanction_id TEXT, date_implemented TEXT, year TEXT, month TEXT,
    imposing_country_code TEXT, imposing_country TEXT, imposing_region TEXT,
    target_country_code TEXT, target_country TEXT, restriction_type TEXT, affected_technology TEXT,
    severity_level TEXT, description TEXT, source_reference TEXT, is_retaliatory TEXT, multilateral TEXT,
    status TEXT, economic_impact_usd_bn_est TEXT, is_synthetic TEXT,
    _batch_id BIGINT NOT NULL REFERENCES import_batch(batch_id), _source_file TEXT NOT NULL, _row_number INT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE raw.budgets (
    budget_id TEXT, country_code TEXT, country TEXT, region TEXT, year TEXT,
    total_ai_investment_usd_bn TEXT, public_investment_pct TEXT, private_investment_pct TEXT,
    public_investment_usd_bn TEXT, private_investment_usd_bn TEXT, datacenter_investment_usd_bn TEXT,
    semiconductor_subsidies_usd_bn TEXT, swf_allocation_usd_bn TEXT, ai_workforce_investment_usd_bn TEXT,
    strategic_initiative TEXT, national_supercomputer_projects TEXT, foreign_tech_restrictions_active TEXT,
    geopolitical_risk_score TEXT, ai_sovereignty_index TEXT, alliance_bloc TEXT, data_source TEXT, is_synthetic TEXT,
    _batch_id BIGINT NOT NULL REFERENCES import_batch(batch_id), _source_file TEXT NOT NULL, _row_number INT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE raw.energy (
    energy_id TEXT, country_code TEXT, country TEXT, region TEXT, year TEXT,
    total_grid_capacity_gw TEXT, ai_datacenter_energy_twh TEXT, pct_grid_used_by_ai TEXT,
    renewable_energy_pct TEXT, non_renewable_energy_pct TEXT, coal_pct TEXT, natural_gas_pct TEXT,
    nuclear_pct TEXT, solar_wind_pct TEXT, hydro_pct TEXT, energy_constraint_level TEXT,
    planned_expansion_gw TEXT, ai_grid_stress_index TEXT, carbon_intensity_gco2_per_kwh TEXT,
    geopolitical_risk_score TEXT, data_source TEXT, is_synthetic TEXT,
    _batch_id BIGINT NOT NULL REFERENCES import_batch(batch_id), _source_file TEXT NOT NULL, _row_number INT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE raw.macro (
    macro_id TEXT, country_code TEXT, country TEXT, region TEXT, alliance_bloc TEXT, year TEXT,
    gdp_usd_bn TEXT, gdp_growth_rate_pct TEXT, inflation_rate_pct TEXT, trade_balance_usd_bn TEXT,
    currency_strength_index TEXT, tech_sector_pct_gdp TEXT, ai_investment_gdp_ratio_pct TEXT,
    dedollarization_index TEXT, foreign_reserves_usd_bn TEXT, semiconductor_exports_usd_bn TEXT,
    unemployment_rate_pct TEXT, geopolitical_risk_score TEXT, ai_sovereignty_index TEXT, data_source TEXT, is_synthetic TEXT,
    _batch_id BIGINT NOT NULL REFERENCES import_batch(batch_id), _source_file TEXT NOT NULL, _row_number INT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE raw.company_profiles (
    company_id TEXT, company_name TEXT, hq_country_code TEXT, hq_country TEXT, primary_domain TEXT,
    year_founded TEXT, strategic_focus TEXT, year TEXT, revenue_usd_bn TEXT, rd_expenditure_usd_bn TEXT,
    employees TEXT, geopolitical_exposure TEXT, sanction_risk_flag TEXT, is_synthetic TEXT,
    _batch_id BIGINT NOT NULL REFERENCES import_batch(batch_id), _source_file TEXT NOT NULL, _row_number INT NOT NULL,
    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
