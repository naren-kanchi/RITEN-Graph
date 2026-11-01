"""The raw archive contract: exact filenames, headers and audited counts.

A source that differs from this is reported and refused rather than silently accepted.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    file: str
    table: str
    id_col: str
    columns: tuple[str, ...]
    rows: int
    synthetic: int


def _cols(text: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in text.split(",") if c.strip())


SOURCES = (
    Source("01_semiconductor_trade_flows.csv", "trade_flows", "trade_id", _cols("""
        trade_id,year,quarter,year_quarter,exporter_country_code,exporter_country,exporter_region,
        importer_country_code,importer_country,importer_region,hardware_type,hardware_category,volume_units,
        trade_value_usd_millions,primary_supplier,trade_route,export_control_applied,restriction_factor,
        geopolitical_sensitivity,geo_risk_score_exporter,geo_risk_score_importer,data_source,is_synthetic"""), 5656, 1008),
    Source("02_trade_sanctions_export_controls.csv", "sanctions", "sanction_id", _cols("""
        sanction_id,date_implemented,year,month,imposing_country_code,imposing_country,imposing_region,
        target_country_code,target_country,restriction_type,affected_technology,severity_level,description,
        source_reference,is_retaliatory,multilateral,status,economic_impact_usd_bn_est,is_synthetic"""), 987, 945),
    Source("03_national_ai_infrastructure_budgets.csv", "budgets", "budget_id", _cols("""
        budget_id,country_code,country,region,year,total_ai_investment_usd_bn,public_investment_pct,
        private_investment_pct,public_investment_usd_bn,private_investment_usd_bn,datacenter_investment_usd_bn,
        semiconductor_subsidies_usd_bn,swf_allocation_usd_bn,ai_workforce_investment_usd_bn,strategic_initiative,
        national_supercomputer_projects,foreign_tech_restrictions_active,geopolitical_risk_score,
        ai_sovereignty_index,alliance_bloc,data_source,is_synthetic"""), 132, 24),
    Source("04_energy_grid_capacity.csv", "energy", "energy_id", _cols("""
        energy_id,country_code,country,region,year,total_grid_capacity_gw,ai_datacenter_energy_twh,
        pct_grid_used_by_ai,renewable_energy_pct,non_renewable_energy_pct,coal_pct,natural_gas_pct,nuclear_pct,
        solar_wind_pct,hydro_pct,energy_constraint_level,planned_expansion_gw,ai_grid_stress_index,
        carbon_intensity_gco2_per_kwh,geopolitical_risk_score,data_source,is_synthetic"""), 132, 24),
    Source("05_macroeconomic_indicators.csv", "macro", "macro_id", _cols("""
        macro_id,country_code,country,region,alliance_bloc,year,gdp_usd_bn,gdp_growth_rate_pct,inflation_rate_pct,
        trade_balance_usd_bn,currency_strength_index,tech_sector_pct_gdp,ai_investment_gdp_ratio_pct,
        dedollarization_index,foreign_reserves_usd_bn,semiconductor_exports_usd_bn,unemployment_rate_pct,
        geopolitical_risk_score,ai_sovereignty_index,data_source,is_synthetic"""), 132, 24),
    Source("06_company_profiles.csv", "company_profiles", "company_id", _cols("""
        company_id,company_name,hq_country_code,hq_country,primary_domain,year_founded,strategic_focus,year,
        revenue_usd_bn,rd_expenditure_usd_bn,employees,geopolitical_exposure,sanction_risk_flag,is_synthetic"""), 242, 44),
)

TOTAL_ROWS = 7281
TOTAL_SYNTHETIC = 2069

# Canonical row counts after normalization: the dimension tables consolidate repeated labels.
EXPECTED_CANONICAL = {
    "geopolitical_actor": 16, "country_profile": 12, "hardware_type": 14, "supplier_label": 40,
    "trade_flow": 5656, "restriction_type": 7, "affected_technology": 55, "restriction_measure": 987,
    "ai_infrastructure_budget": 132, "energy_grid_observation": 132, "macroeconomic_observation": 132,
    "company": 22, "company_year_profile": 242,
}

EXPECTED_GRAPH_NODES = {
    "Actor": 16, "Company": 22, "CompanyYearProfile": 242,
    "AIInfrastructureBudget": 132, "EnergyObservation": 132, "MacroObservation": 132,
}
EXPECTED_GRAPH_RELATIONSHIPS = {
    "TRADE_FLOW": 5656, "IMPOSED": 987, "HEADQUARTERED_IN": 22, "HAS_YEAR_PROFILE": 242,
    "HAS_AI_BUDGET": 132, "HAS_ENERGY_OBSERVATION": 132, "HAS_MACRO_OBSERVATION": 132,
    "TRADE_SUMMARY": 592,
}
