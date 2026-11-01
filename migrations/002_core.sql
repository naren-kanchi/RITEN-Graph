-- Normalized system of record. Monetary and score values use NUMERIC, never binary floats.
-- Domain risk/sovereignty scores stay on their own observation table on purpose: the budget
-- and macro scores disagree in 129 of 132 country-years, so they are not one attribute.
CREATE TABLE geopolitical_actor (
    actor_code VARCHAR(10) PRIMARY KEY,
    actor_name TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('country','regional_organization','global_scope','unresolved_source_actor')),
    review_note TEXT NOT NULL
);
CREATE TABLE country_profile (
    actor_code VARCHAR(10) PRIMARY KEY REFERENCES geopolitical_actor(actor_code),
    region TEXT NOT NULL,
    alliance_bloc TEXT NOT NULL
);
CREATE TABLE hardware_type (
    hardware_type TEXT PRIMARY KEY,
    hardware_category TEXT NOT NULL CHECK (hardware_category IN ('Standard','Advanced'))
);
CREATE TABLE supplier_label (
    supplier_label_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_label TEXT NOT NULL UNIQUE
);
CREATE TABLE trade_flow (
    trade_id VARCHAR(12) PRIMARY KEY,
    year SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    quarter SMALLINT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    exporter_actor_code VARCHAR(10) NOT NULL REFERENCES country_profile(actor_code),
    importer_actor_code VARCHAR(10) NOT NULL REFERENCES country_profile(actor_code),
    hardware_type TEXT NOT NULL REFERENCES hardware_type(hardware_type),
    supplier_label_id INT NOT NULL REFERENCES supplier_label(supplier_label_id),
    volume_units BIGINT NOT NULL CHECK (volume_units >= 0),
    trade_value_usd_millions NUMERIC(14,2) NOT NULL CHECK (trade_value_usd_millions >= 0),
    trade_route TEXT NOT NULL,
    export_control_applied BOOLEAN NOT NULL,
    restriction_factor NUMERIC(4,2) NOT NULL CHECK (restriction_factor > 0 AND restriction_factor <= 1),
    geopolitical_sensitivity TEXT NOT NULL CHECK (geopolitical_sensitivity IN ('Low','Medium','High')),
    geo_risk_score_exporter NUMERIC(5,2) NOT NULL CHECK (geo_risk_score_exporter BETWEEN 0 AND 10),
    geo_risk_score_importer NUMERIC(5,2) NOT NULL CHECK (geo_risk_score_importer BETWEEN 0 AND 10),
    data_source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL,
    CHECK (exporter_actor_code <> importer_actor_code),
    -- Holds on all 5,656 source rows: a control is applied exactly when the factor is below 1.
    CONSTRAINT trade_control_matches_factor CHECK (export_control_applied = (restriction_factor < 1))
);
CREATE TABLE restriction_type (restriction_type TEXT PRIMARY KEY);
CREATE TABLE affected_technology (technology_label TEXT PRIMARY KEY);
CREATE TABLE restriction_measure (
    sanction_id VARCHAR(12) PRIMARY KEY,
    date_implemented DATE NOT NULL,
    imposing_actor_code VARCHAR(10) NOT NULL REFERENCES geopolitical_actor(actor_code),
    target_actor_code VARCHAR(10) NOT NULL REFERENCES geopolitical_actor(actor_code),
    restriction_type TEXT NOT NULL REFERENCES restriction_type(restriction_type),
    affected_technology TEXT NOT NULL REFERENCES affected_technology(technology_label),
    severity_level SMALLINT NOT NULL CHECK (severity_level BETWEEN 1 AND 5),
    description TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    is_retaliatory BOOLEAN NOT NULL,
    multilateral BOOLEAN NOT NULL,
    status TEXT NOT NULL,
    economic_impact_usd_bn_est NUMERIC(10,2) NOT NULL CHECK (economic_impact_usd_bn_est >= 0),
    is_synthetic BOOLEAN NOT NULL,
    CHECK (imposing_actor_code <> target_actor_code)
);
CREATE TABLE ai_infrastructure_budget (
    budget_id VARCHAR(12) PRIMARY KEY,
    actor_code VARCHAR(10) NOT NULL REFERENCES country_profile(actor_code),
    year SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    total_ai_investment_usd_bn NUMERIC(12,3) NOT NULL CHECK (total_ai_investment_usd_bn >= 0),
    public_investment_pct NUMERIC(5,2) NOT NULL CHECK (public_investment_pct BETWEEN 0 AND 100),
    private_investment_pct NUMERIC(5,2) NOT NULL CHECK (private_investment_pct BETWEEN 0 AND 100),
    public_investment_usd_bn NUMERIC(12,3) NOT NULL CHECK (public_investment_usd_bn >= 0),
    private_investment_usd_bn NUMERIC(12,3) NOT NULL CHECK (private_investment_usd_bn >= 0),
    datacenter_investment_usd_bn NUMERIC(12,3) NOT NULL CHECK (datacenter_investment_usd_bn >= 0),
    semiconductor_subsidies_usd_bn NUMERIC(12,3) NOT NULL CHECK (semiconductor_subsidies_usd_bn >= 0),
    swf_allocation_usd_bn NUMERIC(12,3) NOT NULL CHECK (swf_allocation_usd_bn >= 0),
    ai_workforce_investment_usd_bn NUMERIC(12,3) NOT NULL CHECK (ai_workforce_investment_usd_bn >= 0),
    strategic_initiative TEXT NOT NULL,
    national_supercomputer_projects SMALLINT NOT NULL CHECK (national_supercomputer_projects >= 0),
    foreign_tech_restrictions_active BOOLEAN NOT NULL,
    geopolitical_risk_score NUMERIC(5,2) NOT NULL CHECK (geopolitical_risk_score BETWEEN 0 AND 10),
    ai_sovereignty_index NUMERIC(5,2) NOT NULL CHECK (ai_sovereignty_index BETWEEN 0 AND 100),
    data_source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL,
    UNIQUE (actor_code, year),
    CONSTRAINT budget_pct_sum CHECK (public_investment_pct + private_investment_pct = 100)
);
CREATE TABLE energy_grid_observation (
    energy_id VARCHAR(12) PRIMARY KEY,
    actor_code VARCHAR(10) NOT NULL REFERENCES country_profile(actor_code),
    year SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    total_grid_capacity_gw NUMERIC(10,1) NOT NULL CHECK (total_grid_capacity_gw >= 0),
    ai_datacenter_energy_twh NUMERIC(10,2) NOT NULL CHECK (ai_datacenter_energy_twh >= 0),
    pct_grid_used_by_ai NUMERIC(6,2) NOT NULL CHECK (pct_grid_used_by_ai BETWEEN 0 AND 100),
    renewable_energy_pct NUMERIC(5,1) NOT NULL CHECK (renewable_energy_pct BETWEEN 0 AND 100),
    non_renewable_energy_pct NUMERIC(5,1) NOT NULL CHECK (non_renewable_energy_pct BETWEEN 0 AND 100),
    -- No >=0 or sum-to-100 CHECK on the mix: the source holds small negatives and rows that
    -- miss 100 by up to 9.5 points. They are reported as caveats, not rejected or rewritten.
    coal_pct NUMERIC(5,1) NOT NULL,
    natural_gas_pct NUMERIC(5,1) NOT NULL,
    nuclear_pct NUMERIC(5,1) NOT NULL,
    solar_wind_pct NUMERIC(5,1) NOT NULL,
    hydro_pct NUMERIC(5,1) NOT NULL,
    energy_constraint_level TEXT NOT NULL CHECK (energy_constraint_level IN ('Low','Moderate','High','Severe')),
    planned_expansion_gw NUMERIC(10,1) NOT NULL CHECK (planned_expansion_gw >= 0),
    ai_grid_stress_index NUMERIC(6,2) NOT NULL CHECK (ai_grid_stress_index >= 0),
    carbon_intensity_gco2_per_kwh NUMERIC(7,1) NOT NULL CHECK (carbon_intensity_gco2_per_kwh >= 0),
    geopolitical_risk_score NUMERIC(5,2) NOT NULL CHECK (geopolitical_risk_score BETWEEN 0 AND 10),
    data_source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL,
    UNIQUE (actor_code, year)
);
CREATE TABLE macroeconomic_observation (
    macro_id VARCHAR(12) PRIMARY KEY,
    actor_code VARCHAR(10) NOT NULL REFERENCES country_profile(actor_code),
    year SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    gdp_usd_bn NUMERIC(12,1) NOT NULL CHECK (gdp_usd_bn >= 0),
    gdp_growth_rate_pct NUMERIC(6,2) NOT NULL,
    inflation_rate_pct NUMERIC(6,2) NOT NULL,
    trade_balance_usd_bn NUMERIC(10,2) NOT NULL,
    currency_strength_index NUMERIC(6,2) NOT NULL,
    tech_sector_pct_gdp NUMERIC(5,2) NOT NULL CHECK (tech_sector_pct_gdp BETWEEN 0 AND 100),
    ai_investment_gdp_ratio_pct NUMERIC(8,4) NOT NULL CHECK (ai_investment_gdp_ratio_pct >= 0),
    dedollarization_index NUMERIC(6,2) NOT NULL,
    foreign_reserves_usd_bn NUMERIC(10,1) NOT NULL CHECK (foreign_reserves_usd_bn >= 0),
    semiconductor_exports_usd_bn NUMERIC(10,2) NOT NULL CHECK (semiconductor_exports_usd_bn >= 0),
    unemployment_rate_pct NUMERIC(5,2) NOT NULL CHECK (unemployment_rate_pct BETWEEN 0 AND 100),
    geopolitical_risk_score NUMERIC(5,2) NOT NULL CHECK (geopolitical_risk_score BETWEEN 0 AND 10),
    ai_sovereignty_index NUMERIC(5,2) NOT NULL CHECK (ai_sovereignty_index BETWEEN 0 AND 100),
    data_source TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL,
    UNIQUE (actor_code, year)
);
CREATE TABLE company (
    company_key INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_name TEXT NOT NULL,
    hq_actor_code VARCHAR(10) NOT NULL REFERENCES country_profile(actor_code),
    primary_domain TEXT NOT NULL,
    year_founded SMALLINT NOT NULL CHECK (year_founded BETWEEN 1800 AND 2100),
    strategic_focus TEXT NOT NULL
);
CREATE UNIQUE INDEX company_identity_uq ON company (lower(trim(company_name)), hq_actor_code);
CREATE TABLE company_year_profile (
    source_profile_id VARCHAR(12) PRIMARY KEY,
    company_key INT NOT NULL REFERENCES company(company_key),
    year SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    revenue_usd_bn NUMERIC(10,2) NOT NULL CHECK (revenue_usd_bn >= 0),
    rd_expenditure_usd_bn NUMERIC(10,2) NOT NULL CHECK (rd_expenditure_usd_bn >= 0),
    employees INT NOT NULL CHECK (employees >= 0),
    geopolitical_exposure TEXT NOT NULL CHECK (geopolitical_exposure IN ('Low','Medium','High')),
    sanction_risk_flag BOOLEAN NOT NULL,
    is_synthetic BOOLEAN NOT NULL,
    UNIQUE (company_key, year)
);
