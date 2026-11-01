-- year_quarter is derived here rather than stored, so it can never disagree with year + quarter.
CREATE VIEW v_trade_flow AS
SELECT t.trade_id, t.year, t.quarter, t.year || '-Q' || t.quarter AS year_quarter,
       t.exporter_actor_code, ex.actor_name AS exporter_name,
       t.importer_actor_code, im.actor_name AS importer_name,
       t.hardware_type, h.hardware_category, s.supplier_label,
       t.volume_units, t.trade_value_usd_millions, t.trade_route,
       t.export_control_applied, t.restriction_factor, t.geopolitical_sensitivity,
       t.geo_risk_score_exporter, t.geo_risk_score_importer, t.data_source, t.is_synthetic
FROM trade_flow t
JOIN geopolitical_actor ex ON ex.actor_code = t.exporter_actor_code
JOIN geopolitical_actor im ON im.actor_code = t.importer_actor_code
JOIN hardware_type h ON h.hardware_type = t.hardware_type
JOIN supplier_label s ON s.supplier_label_id = t.supplier_label_id;

CREATE VIEW v_annual_trade_link AS
SELECT t.year, t.exporter_actor_code, t.importer_actor_code,
       SUM(t.trade_value_usd_millions) AS total_value_usd_millions,
       SUM(t.volume_units) AS total_volume_units,
       COUNT(*) AS observations,
       COUNT(*) FILTER (WHERE t.export_control_applied) AS controlled_observations,
       BOOL_OR(t.is_synthetic) AS is_synthetic
FROM trade_flow t
GROUP BY t.year, t.exporter_actor_code, t.importer_actor_code;

-- One row per country-year. Scores keep a domain prefix because they are different measures.
CREATE VIEW v_country_year_comparison AS
SELECT a.actor_code, a.actor_name, c.region, c.alliance_bloc, b.year,
       b.total_ai_investment_usd_bn, b.datacenter_investment_usd_bn, b.semiconductor_subsidies_usd_bn,
       b.swf_allocation_usd_bn, b.national_supercomputer_projects, b.strategic_initiative,
       b.geopolitical_risk_score AS budget_risk_score, b.ai_sovereignty_index AS budget_sovereignty_index,
       e.total_grid_capacity_gw, e.ai_datacenter_energy_twh, e.pct_grid_used_by_ai, e.ai_grid_stress_index,
       e.energy_constraint_level, e.planned_expansion_gw, e.renewable_energy_pct,
       e.geopolitical_risk_score AS energy_risk_score,
       m.gdp_usd_bn, m.gdp_growth_rate_pct, m.tech_sector_pct_gdp, m.dedollarization_index,
       m.foreign_reserves_usd_bn, m.semiconductor_exports_usd_bn,
       m.geopolitical_risk_score AS macro_risk_score, m.ai_sovereignty_index AS macro_sovereignty_index,
       (b.is_synthetic OR e.is_synthetic OR m.is_synthetic) AS is_synthetic
FROM ai_infrastructure_budget b
JOIN energy_grid_observation e ON e.actor_code = b.actor_code AND e.year = b.year
JOIN macroeconomic_observation m ON m.actor_code = b.actor_code AND m.year = b.year
JOIN country_profile c ON c.actor_code = b.actor_code
JOIN geopolitical_actor a ON a.actor_code = b.actor_code;

-- Exposes approved aliases only, so unreviewed proposals cannot leak into reports.
CREATE VIEW v_company_supplier_trade AS
SELECT co.company_key, co.company_name, l.supplier_label, t.year,
       SUM(t.trade_value_usd_millions) AS total_value_usd_millions,
       COUNT(*) AS observations,
       COUNT(*) FILTER (WHERE t.export_control_applied) AS controlled_observations,
       BOOL_OR(t.is_synthetic) AS is_synthetic
FROM supplier_company_alias al
JOIN company co ON co.company_key = al.company_key
JOIN supplier_label l ON l.supplier_label_id = al.supplier_label_id
JOIN trade_flow t ON t.supplier_label_id = al.supplier_label_id
WHERE al.status = 'approved'
GROUP BY co.company_key, co.company_name, l.supplier_label, t.year;
