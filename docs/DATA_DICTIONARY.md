# Data dictionary

Generated from the live database catalog by `python scripts/gen_docs.py`, so it cannot drift from the DDL.

The `raw` schema holds one all-text staging table per CSV, using the exact source column names, plus `_batch_id`, `_source_file`, `_row_number` and `_loaded_at`.

## `geopolitical_actor`

Every code that appears in the source: countries, the EU, GLOBAL, and the unresolved IR and RU labels.

Rows: 16

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `actor_code` | varchar(10) | no | PK |  |
| `actor_name` | text | no |  |  |
| `actor_type` | text | no |  |  |
| `review_note` | text | no |  |  |

Constraints:

- `CHECK ((actor_type = ANY (ARRAY['country'::text, 'regional_organization'::text, 'global_scope'::text, 'unresolved_source_actor'::text])))`

## `country_profile`

Optional subtype of actor for the 12 codes with country-year data.

Rows: 12

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `actor_code` | varchar(10) | no | PK | geopolitical_actor.actor_code |
| `region` | text | no |  |  |
| `alliance_bloc` | text | no |  |  |

## `hardware_type`

Hardware dimension. `hardware_category` depends only on `hardware_type`.

Rows: 14

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `hardware_type` | text | no | PK |  |
| `hardware_category` | text | no |  |  |

Constraints:

- `CHECK ((hardware_category = ANY (ARRAY['Standard'::text, 'Advanced'::text])))`

## `supplier_label`

Exact supplier strings from the trade file. Labels, not companies.

Rows: 40

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `supplier_label_id` | integer | no | PK |  |
| `supplier_label` | text | no |  |  |

Constraints:

- `UNIQUE (supplier_label)`

## `trade_flow`

One quarterly trade observation per exporter, importer and hardware type.

Rows: 5,656

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `trade_id` | varchar(12) | no | PK |  |
| `year` | smallint | no |  |  |
| `quarter` | smallint | no |  |  |
| `exporter_actor_code` | varchar(10) | no |  | country_profile.actor_code |
| `importer_actor_code` | varchar(10) | no |  | country_profile.actor_code |
| `hardware_type` | text | no |  | hardware_type.hardware_type |
| `supplier_label_id` | integer | no |  | supplier_label.supplier_label_id |
| `volume_units` | bigint | no |  |  |
| `trade_value_usd_millions` | numeric(14,2) | no |  |  |
| `trade_route` | text | no |  |  |
| `export_control_applied` | boolean | no |  |  |
| `restriction_factor` | numeric(4,2) | no |  |  |
| `geopolitical_sensitivity` | text | no |  |  |
| `geo_risk_score_exporter` | numeric(5,2) | no |  |  |
| `geo_risk_score_importer` | numeric(5,2) | no |  |  |
| `data_source` | text | no |  |  |
| `is_synthetic` | boolean | no |  |  |

Constraints:

- `CHECK ((export_control_applied = (restriction_factor < (1)::numeric)))`
- `CHECK (((exporter_actor_code)::text <> (importer_actor_code)::text))`
- `CHECK (((geo_risk_score_exporter >= (0)::numeric) AND (geo_risk_score_exporter <= (10)::numeric)))`
- `CHECK (((geo_risk_score_importer >= (0)::numeric) AND (geo_risk_score_importer <= (10)::numeric)))`
- `CHECK ((geopolitical_sensitivity = ANY (ARRAY['Low'::text, 'Medium'::text, 'High'::text])))`
- `CHECK (((quarter >= 1) AND (quarter <= 4)))`
- `CHECK (((restriction_factor > (0)::numeric) AND (restriction_factor <= (1)::numeric)))`
- `CHECK ((trade_value_usd_millions >= (0)::numeric))`
- `CHECK ((volume_units >= 0))`
- `CHECK (((year >= 2000) AND (year <= 2100)))`
- `UNIQUE (year, quarter, exporter_actor_code, importer_actor_code, hardware_type)`

Indexes:

- `INDEX trade_controlled_idx ON trade_flow USING btree (year, exporter_actor_code) WHERE export_control_applied`
- `INDEX trade_hardware_year_idx ON trade_flow USING btree (hardware_type, year)`
- `INDEX trade_importer_year_idx ON trade_flow USING btree (importer_actor_code, year)`
- `INDEX trade_pair_year_idx ON trade_flow USING btree (exporter_actor_code, importer_actor_code, year)`
- `INDEX trade_period_idx ON trade_flow USING btree (year, quarter)`
- `INDEX trade_supplier_idx ON trade_flow USING btree (supplier_label_id)`

## `restriction_type`

The seven restriction types in the source.

Rows: 7

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `restriction_type` | text | no | PK |  |

## `affected_technology`

The 55 technology labels in the source. Never matched automatically to hardware types.

Rows: 55

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `technology_label` | text | no | PK |  |

## `restriction_measure`

One sanction or export-control measure from an imposing actor to a target actor.

Rows: 987

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `sanction_id` | varchar(12) | no | PK |  |
| `date_implemented` | date | no |  |  |
| `imposing_actor_code` | varchar(10) | no |  | geopolitical_actor.actor_code |
| `target_actor_code` | varchar(10) | no |  | geopolitical_actor.actor_code |
| `restriction_type` | text | no |  | restriction_type.restriction_type |
| `affected_technology` | text | no |  | affected_technology.technology_label |
| `severity_level` | smallint | no |  |  |
| `description` | text | no |  |  |
| `source_reference` | text | no |  |  |
| `is_retaliatory` | boolean | no |  |  |
| `multilateral` | boolean | no |  |  |
| `status` | text | no |  |  |
| `economic_impact_usd_bn_est` | numeric(10,2) | no |  |  |
| `is_synthetic` | boolean | no |  |  |
| `search_vector` | tsvector | yes |  |  |

Constraints:

- `CHECK (((imposing_actor_code)::text <> (target_actor_code)::text))`
- `CHECK ((economic_impact_usd_bn_est >= (0)::numeric))`
- `CHECK (((severity_level >= 1) AND (severity_level <= 5)))`

Indexes:

- `INDEX restriction_imposer_date_idx ON restriction_measure USING btree (imposing_actor_code, date_implemented)`
- `INDEX restriction_search_idx ON restriction_measure USING gin (search_vector)`
- `INDEX restriction_target_date_idx ON restriction_measure USING btree (target_actor_code, date_implemented)`

## `ai_infrastructure_budget`

Annual national AI investment, per country.

Rows: 132

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `budget_id` | varchar(12) | no | PK |  |
| `actor_code` | varchar(10) | no |  | country_profile.actor_code |
| `year` | smallint | no |  |  |
| `total_ai_investment_usd_bn` | numeric(12,3) | no |  |  |
| `public_investment_pct` | numeric(5,2) | no |  |  |
| `private_investment_pct` | numeric(5,2) | no |  |  |
| `public_investment_usd_bn` | numeric(12,3) | no |  |  |
| `private_investment_usd_bn` | numeric(12,3) | no |  |  |
| `datacenter_investment_usd_bn` | numeric(12,3) | no |  |  |
| `semiconductor_subsidies_usd_bn` | numeric(12,3) | no |  |  |
| `swf_allocation_usd_bn` | numeric(12,3) | no |  |  |
| `ai_workforce_investment_usd_bn` | numeric(12,3) | no |  |  |
| `strategic_initiative` | text | no |  |  |
| `national_supercomputer_projects` | smallint | no |  |  |
| `foreign_tech_restrictions_active` | boolean | no |  |  |
| `geopolitical_risk_score` | numeric(5,2) | no |  |  |
| `ai_sovereignty_index` | numeric(5,2) | no |  |  |
| `data_source` | text | no |  |  |
| `is_synthetic` | boolean | no |  |  |

Constraints:

- `CHECK (((ai_sovereignty_index >= (0)::numeric) AND (ai_sovereignty_index <= (100)::numeric)))`
- `CHECK ((ai_workforce_investment_usd_bn >= (0)::numeric))`
- `CHECK ((datacenter_investment_usd_bn >= (0)::numeric))`
- `CHECK (((geopolitical_risk_score >= (0)::numeric) AND (geopolitical_risk_score <= (10)::numeric)))`
- `CHECK ((national_supercomputer_projects >= 0))`
- `CHECK (((private_investment_pct >= (0)::numeric) AND (private_investment_pct <= (100)::numeric)))`
- `CHECK ((private_investment_usd_bn >= (0)::numeric))`
- `CHECK (((public_investment_pct >= (0)::numeric) AND (public_investment_pct <= (100)::numeric)))`
- `CHECK ((public_investment_usd_bn >= (0)::numeric))`
- `CHECK ((semiconductor_subsidies_usd_bn >= (0)::numeric))`
- `CHECK ((swf_allocation_usd_bn >= (0)::numeric))`
- `CHECK ((total_ai_investment_usd_bn >= (0)::numeric))`
- `CHECK (((year >= 2000) AND (year <= 2100)))`
- `CHECK (((public_investment_pct + private_investment_pct) = (100)::numeric))`
- `UNIQUE (actor_code, year)`

## `energy_grid_observation`

Annual grid capacity and AI energy use, per country.

Rows: 132

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `energy_id` | varchar(12) | no | PK |  |
| `actor_code` | varchar(10) | no |  | country_profile.actor_code |
| `year` | smallint | no |  |  |
| `total_grid_capacity_gw` | numeric(10,1) | no |  |  |
| `ai_datacenter_energy_twh` | numeric(10,2) | no |  |  |
| `pct_grid_used_by_ai` | numeric(6,2) | no |  |  |
| `renewable_energy_pct` | numeric(5,1) | no |  |  |
| `non_renewable_energy_pct` | numeric(5,1) | no |  |  |
| `coal_pct` | numeric(5,1) | no |  |  |
| `natural_gas_pct` | numeric(5,1) | no |  |  |
| `nuclear_pct` | numeric(5,1) | no |  |  |
| `solar_wind_pct` | numeric(5,1) | no |  |  |
| `hydro_pct` | numeric(5,1) | no |  |  |
| `energy_constraint_level` | text | no |  |  |
| `planned_expansion_gw` | numeric(10,1) | no |  |  |
| `ai_grid_stress_index` | numeric(6,2) | no |  |  |
| `carbon_intensity_gco2_per_kwh` | numeric(7,1) | no |  |  |
| `geopolitical_risk_score` | numeric(5,2) | no |  |  |
| `data_source` | text | no |  |  |
| `is_synthetic` | boolean | no |  |  |

Constraints:

- `CHECK ((ai_datacenter_energy_twh >= (0)::numeric))`
- `CHECK ((ai_grid_stress_index >= (0)::numeric))`
- `CHECK ((carbon_intensity_gco2_per_kwh >= (0)::numeric))`
- `CHECK ((energy_constraint_level = ANY (ARRAY['Low'::text, 'Moderate'::text, 'High'::text, 'Severe'::text])))`
- `CHECK (((geopolitical_risk_score >= (0)::numeric) AND (geopolitical_risk_score <= (10)::numeric)))`
- `CHECK (((non_renewable_energy_pct >= (0)::numeric) AND (non_renewable_energy_pct <= (100)::numeric)))`
- `CHECK (((pct_grid_used_by_ai >= (0)::numeric) AND (pct_grid_used_by_ai <= (100)::numeric)))`
- `CHECK ((planned_expansion_gw >= (0)::numeric))`
- `CHECK (((renewable_energy_pct >= (0)::numeric) AND (renewable_energy_pct <= (100)::numeric)))`
- `CHECK ((total_grid_capacity_gw >= (0)::numeric))`
- `CHECK (((year >= 2000) AND (year <= 2100)))`
- `UNIQUE (actor_code, year)`

## `macroeconomic_observation`

Annual macroeconomic indicators, per country.

Rows: 132

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `macro_id` | varchar(12) | no | PK |  |
| `actor_code` | varchar(10) | no |  | country_profile.actor_code |
| `year` | smallint | no |  |  |
| `gdp_usd_bn` | numeric(12,1) | no |  |  |
| `gdp_growth_rate_pct` | numeric(6,2) | no |  |  |
| `inflation_rate_pct` | numeric(6,2) | no |  |  |
| `trade_balance_usd_bn` | numeric(10,2) | no |  |  |
| `currency_strength_index` | numeric(6,2) | no |  |  |
| `tech_sector_pct_gdp` | numeric(5,2) | no |  |  |
| `ai_investment_gdp_ratio_pct` | numeric(8,4) | no |  |  |
| `dedollarization_index` | numeric(6,2) | no |  |  |
| `foreign_reserves_usd_bn` | numeric(10,1) | no |  |  |
| `semiconductor_exports_usd_bn` | numeric(10,2) | no |  |  |
| `unemployment_rate_pct` | numeric(5,2) | no |  |  |
| `geopolitical_risk_score` | numeric(5,2) | no |  |  |
| `ai_sovereignty_index` | numeric(5,2) | no |  |  |
| `data_source` | text | no |  |  |
| `is_synthetic` | boolean | no |  |  |

Constraints:

- `CHECK ((ai_investment_gdp_ratio_pct >= (0)::numeric))`
- `CHECK (((ai_sovereignty_index >= (0)::numeric) AND (ai_sovereignty_index <= (100)::numeric)))`
- `CHECK ((foreign_reserves_usd_bn >= (0)::numeric))`
- `CHECK ((gdp_usd_bn >= (0)::numeric))`
- `CHECK (((geopolitical_risk_score >= (0)::numeric) AND (geopolitical_risk_score <= (10)::numeric)))`
- `CHECK ((semiconductor_exports_usd_bn >= (0)::numeric))`
- `CHECK (((tech_sector_pct_gdp >= (0)::numeric) AND (tech_sector_pct_gdp <= (100)::numeric)))`
- `CHECK (((unemployment_rate_pct >= (0)::numeric) AND (unemployment_rate_pct <= (100)::numeric)))`
- `CHECK (((year >= 2000) AND (year <= 2100)))`
- `UNIQUE (actor_code, year)`

## `company`

Stable company identity. The source's `company_id` changes every year, so it cannot be this key.

Rows: 22

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `company_key` | integer | no | PK |  |
| `company_name` | text | no |  |  |
| `hq_actor_code` | varchar(10) | no |  | country_profile.actor_code |
| `primary_domain` | text | no |  |  |
| `year_founded` | smallint | no |  |  |
| `strategic_focus` | text | no |  |  |

Constraints:

- `CHECK (((year_founded >= 1800) AND (year_founded <= 2100)))`

Indexes:

- `INDEX company_hq_idx ON company USING btree (hq_actor_code)`
- `UNIQUE INDEX company_identity_uq ON company USING btree (lower(TRIM(BOTH FROM company_name)), hq_actor_code)`

## `company_year_profile`

One annual company record, keyed by the source's annual ID.

Rows: 242

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `source_profile_id` | varchar(12) | no | PK |  |
| `company_key` | integer | no |  | company.company_key |
| `year` | smallint | no |  |  |
| `revenue_usd_bn` | numeric(10,2) | no |  |  |
| `rd_expenditure_usd_bn` | numeric(10,2) | no |  |  |
| `employees` | integer | no |  |  |
| `geopolitical_exposure` | text | no |  |  |
| `sanction_risk_flag` | boolean | no |  |  |
| `is_synthetic` | boolean | no |  |  |

Constraints:

- `CHECK ((employees >= 0))`
- `CHECK ((geopolitical_exposure = ANY (ARRAY['Low'::text, 'Medium'::text, 'High'::text])))`
- `CHECK ((rd_expenditure_usd_bn >= (0)::numeric))`
- `CHECK ((revenue_usd_bn >= (0)::numeric))`
- `CHECK (((year >= 2000) AND (year <= 2100)))`
- `UNIQUE (company_key, year)`

## `app_user`

Accounts and roles. Only Argon2 hashes can be stored.

Rows: 2

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `user_id` | integer | no | PK |  |
| `username` | varchar(40) | no |  |  |
| `password_hash` | text | no |  |  |
| `role` | text | no |  |  |
| `is_active` | boolean | no |  |  |
| `created_at` | timestamp with time zone | no |  |  |

Constraints:

- `CHECK ((password_hash ~~ '$argon2%'::text))`
- `CHECK ((role = ANY (ARRAY['analyst'::text, 'admin'::text])))`
- `CHECK (((username)::text ~ '^[A-Za-z0-9_.-]{3,40}$'::text))`
- `UNIQUE (username)`

## `annotation`

Notes people attach to records. Source facts stay untouched.

Rows: 0

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `annotation_id` | bigint | no | PK |  |
| `entity_type` | text | no |  |  |
| `entity_key` | text | no |  |  |
| `note` | text | no |  |  |
| `created_by` | integer | no |  | app_user.user_id |
| `created_at` | timestamp with time zone | no |  |  |
| `updated_at` | timestamp with time zone | no |  |  |

Constraints:

- `CHECK (((length(entity_key) >= 1) AND (length(entity_key) <= 40)))`
- `CHECK ((entity_type = ANY (ARRAY['actor'::text, 'trade_flow'::text, 'restriction'::text, 'company'::text])))`
- `CHECK (((length(TRIM(BOTH FROM note)) >= 1) AND (length(TRIM(BOTH FROM note)) <= 2000)))`

Indexes:

- `INDEX annotation_entity_idx ON annotation USING btree (entity_type, entity_key)`

## `supplier_company_alias`

Reviewed mapping from a supplier label to a company, with evidence and approval.

Rows: 0

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `alias_id` | bigint | no | PK |  |
| `supplier_label_id` | integer | no |  | supplier_label.supplier_label_id |
| `company_key` | integer | no |  | company.company_key |
| `evidence` | text | no |  |  |
| `confidence` | text | no |  |  |
| `status` | text | no |  |  |
| `proposed_by` | integer | no |  | app_user.user_id |
| `reviewed_by` | integer | yes |  | app_user.user_id |
| `reviewed_at` | timestamp with time zone | yes |  |  |
| `created_at` | timestamp with time zone | no |  |  |

Constraints:

- `CHECK ((((status = 'proposed'::text) AND (reviewed_by IS NULL) AND (reviewed_at IS NULL)) OR ((status <> 'proposed'::text) AND (reviewed_by IS NOT NULL) AND (reviewed_at IS NOT NULL))))`
- `CHECK ((confidence = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])))`
- `CHECK ((length(TRIM(BOTH FROM evidence)) >= 10))`
- `CHECK ((status = ANY (ARRAY['proposed'::text, 'approved'::text, 'rejected'::text])))`

Indexes:

- `UNIQUE INDEX alias_one_approved_uq ON supplier_company_alias USING btree (supplier_label_id) WHERE (status = 'approved'::text)`
- `INDEX alias_status_idx ON supplier_company_alias USING btree (status, supplier_label_id)`

## `audit_log`

Written only by triggers: who changed which note or alias, before and after.

Rows: 12

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `audit_id` | bigint | no | PK |  |
| `table_name` | text | no |  |  |
| `operation` | text | no |  |  |
| `row_pk` | text | no |  |  |
| `old_row` | jsonb | yes |  |  |
| `new_row` | jsonb | yes |  |  |
| `acting_user_id` | integer | yes |  |  |
| `logged_at` | timestamp with time zone | no |  |  |

Constraints:

- `CHECK ((operation = ANY (ARRAY['INSERT'::text, 'UPDATE'::text, 'DELETE'::text])))`

Indexes:

- `INDEX audit_logged_idx ON audit_log USING btree (logged_at DESC)`

## `import_batch`

One row per import attempt, including failures.

Rows: 10

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `batch_id` | bigint | no | PK |  |
| `started_at` | timestamp with time zone | no |  |  |
| `finished_at` | timestamp with time zone | yes |  |  |
| `status` | text | no |  |  |
| `row_counts` | jsonb | no |  |  |
| `triggered_by` | text | no |  |  |
| `data_version` | text | yes |  |  |

Constraints:

- `CHECK ((status = ANY (ARRAY['running'::text, 'succeeded'::text, 'failed'::text])))`

## `etl_issue`

Blocking errors and disclosed caveats found by import rules.

Rows: 2,120

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `issue_id` | bigint | no | PK |  |
| `batch_id` | bigint | no |  | import_batch.batch_id |
| `severity` | text | no |  |  |
| `rule` | text | no |  |  |
| `source_file` | text | no |  |  |
| `source_id` | text | yes |  |  |
| `detail` | text | no |  |  |

Constraints:

- `CHECK ((severity = ANY (ARRAY['error'::text, 'caveat'::text])))`

Indexes:

- `INDEX etl_issue_batch_idx ON etl_issue USING btree (batch_id, severity, rule)`

## `navigation_event`

Anonymous view events for the prefetch predictor.

Rows: 0

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `event_id` | bigint | no | PK |  |
| `session_id` | varchar(64) | no |  |  |
| `view_type` | text | no |  |  |
| `entity_key` | varchar(40) | no |  |  |
| `client_event_id` | varchar(64) | yes |  |  |
| `occurred_at` | timestamp with time zone | no |  |  |

Constraints:

- `CHECK ((view_type = ANY (ARRAY['actor_profile'::text, 'graph_neighborhood'::text])))`

Indexes:

- `UNIQUE INDEX navigation_replay_uq ON navigation_event USING btree (session_id, client_event_id) WHERE (client_event_id IS NOT NULL)`
- `INDEX navigation_session_idx ON navigation_event USING btree (session_id, occurred_at, event_id)`

## `prefetch_stat`

Each prefetched cache entry and whether it was later used.

Rows: 0

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `prefetch_id` | bigint | no | PK |  |
| `cache_key` | text | no |  |  |
| `prefetched_at` | timestamp with time zone | no |  |  |
| `payload_bytes` | integer | no |  |  |
| `used_at` | timestamp with time zone | yes |  |  |

Constraints:

- `CHECK ((payload_bytes >= 0))`

Indexes:

- `INDEX prefetch_key_idx ON prefetch_stat USING btree (cache_key, prefetched_at DESC)`

## `schema_migration`

Migrations already applied.

Rows: 9

| Column | Type | Null | Key | References |
|---|---|---|---|---|
| `version` | text | no | PK |  |
| `applied_at` | timestamp with time zone | no |  |  |

## Views

- `v_annual_trade_link`
- `v_company_supplier_trade`
- `v_country_year_comparison`
- `v_trade_flow`

Definitions are in `migrations/006_views.sql`.

## Triggers

- `alias_audit` on `supplier_company_alias`
- `alias_review_guard` on `supplier_company_alias`
- `annotation_audit` on `annotation`
- `annotation_touch` on `annotation`

Definitions are in `migrations/007_functions_triggers.sql`.
