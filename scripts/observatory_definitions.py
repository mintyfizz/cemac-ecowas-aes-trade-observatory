"""Shared definitions for the CEMAC-ECOWAS-AES Trade Observatory.

The offline rebuild (scripts/offline_rebuild.py), the static contract checks
(scripts/check_static_contract.py) and the Databricks notebooks implement the
same rules. When a rule changes here, change the matching notebook cell too
(see docs/methodology.md for the cross-reference).
"""

from __future__ import annotations

import csv
import math
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"

START_YEAR = 1990
END_YEAR = 2024

# --------------------------------------------------------------------------
# Countries and analytical membership (mirrors notebook 08)
# --------------------------------------------------------------------------
BLOC_NAMES = {
    "CEMAC": "Economic and Monetary Community of Central Africa",
    "ECOWAS": "Economic Community of West African States",
    "AES": "Alliance of Sahel States",
}

# iso3: (display name, region, current analytical bloc)
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "CMR": ("Cameroon", "Central Africa", "CEMAC"),
    "CAF": ("Central African Republic", "Central Africa", "CEMAC"),
    "TCD": ("Chad", "Central Africa", "CEMAC"),
    "COG": ("Congo, Rep.", "Central Africa", "CEMAC"),
    "GNQ": ("Equatorial Guinea", "Central Africa", "CEMAC"),
    "GAB": ("Gabon", "Central Africa", "CEMAC"),
    "BEN": ("Benin", "West Africa", "ECOWAS"),
    "BFA": ("Burkina Faso", "West Africa", "AES"),
    "CPV": ("Cabo Verde", "West Africa", "ECOWAS"),
    "CIV": ("Cote d'Ivoire", "West Africa", "ECOWAS"),
    "GMB": ("Gambia", "West Africa", "ECOWAS"),
    "GHA": ("Ghana", "West Africa", "ECOWAS"),
    "GIN": ("Guinea", "West Africa", "ECOWAS"),
    "GNB": ("Guinea-Bissau", "West Africa", "ECOWAS"),
    "LBR": ("Liberia", "West Africa", "ECOWAS"),
    "MLI": ("Mali", "West Africa", "AES"),
    "NER": ("Niger", "West Africa", "AES"),
    "NGA": ("Nigeria", "West Africa", "ECOWAS"),
    "SEN": ("Senegal", "West Africa", "ECOWAS"),
    "SLE": ("Sierra Leone", "West Africa", "ECOWAS"),
    "TGO": ("Togo", "West Africa", "ECOWAS"),
}

AES_MEMBERS = {"BFA", "MLI", "NER"}
# Analytical cohort rule (notebook 08): AES from the confederation treaty
# (6 Jul 2024). Legal ECOWAS withdrawal took effect 29 Jan 2025. This is an
# analytical grouping, not a statement of legal membership.
AES_ANALYTICAL_START = date(2024, 7, 6)
ECOWAS_LEGAL_EXIT_AES = date(2025, 1, 29)

MEMBERSHIP_RULE = (
    "Annual rows use the analytical bloc valid on 31 December of that year. "
    "Burkina Faso, Mali and Niger are grouped as AES from the AES confederation "
    "treaty (6 July 2024); their legal ECOWAS withdrawal took effect on 29 January "
    "2025. Other members are back-cast to 1990 for longitudinal comparison."
)


def analytical_bloc(iso3: str, year: int) -> tuple[str, str]:
    """Return (bloc_code, membership_basis) for a country-year."""
    if iso3 in AES_MEMBERS:
        if date(year, 12, 31) >= AES_ANALYTICAL_START:
            return "AES", "analytical_aes_cohort_from_2024_07_06"
        return "ECOWAS", "analytical_ecowas_before_aes_cohort"
    return COUNTRIES[iso3][2], "current_member_backcast"


def bloc_members(bloc: str, year: int) -> list[str]:
    return sorted(c for c in COUNTRIES if analytical_bloc(c, year)[0] == bloc)


# --------------------------------------------------------------------------
# IMF IMTS counterpart roles (reviewed codelist, not a regex)
# --------------------------------------------------------------------------
IMTS_WORLD_CODE = "G001"
EXPORT_INDICATOR = "XG_FOB_USD"
IMPORT_INDICATOR = "MG_CIF_USD"


def load_counterpart_roles() -> dict[str, dict[str, str]]:
    path = CONFIG / "imts_counterpart_roles.csv"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    return {row["code"]: row for row in csv.DictReader(lines)}


# --------------------------------------------------------------------------
# ACLED (mirrors notebooks 05/11/15)
# --------------------------------------------------------------------------
VIOLENT_EVENT_TYPES = (
    "Battles",
    "Explosions/Remote violence",
    "Violence against civilians",
    "Riots",
)
HOTSPOT_WINDOW = (2022, 2024)  # fixed, complete calendar years

# --------------------------------------------------------------------------
# WEO and FSI
# --------------------------------------------------------------------------
WEO_COLUMNS = {
    "NGDPD": "gdp_current_usd",
    "LP": "population_persons",
    "NGDPDPC": "gdp_per_capita_current_usd",
    "NGDP_RPCH": "real_gdp_growth_pct_imf",
    "PCPIPCH": "inflation_cpi_pct",
    "GGXWDG_NGDP": "gross_debt_pct_gdp_imf",
    "GGR_NGDP": "government_revenue_pct_gdp_imf",
    "GGX_NGDP": "government_expenditure_pct_gdp_imf",
    "GGXCNL_NGDP": "net_lending_borrowing_pct_gdp_imf",
    "BCA_NGDPD": "current_account_balance_pct_gdp_imf",
}

FSI_COLUMNS = {
    "TOTAL": "fsi_total_score",
    "C1": "security_apparatus_score",
    "C2": "factionalized_elites_score",
    "C3": "group_grievance_score",
    "E1": "economic_decline_score",
    "E2": "uneven_economic_development_score",
    "E3": "human_flight_brain_drain_score",
    "P1": "state_legitimacy_score",
    "P2": "public_services_score",
    "P3": "human_rights_rule_of_law_score",
    "S1": "demographic_pressures_score",
    "S2": "refugees_idps_score",
    "X1": "external_intervention_score",
}
FSI_PILLARS = {
    "cohesion_score": ("C1", "C2", "C3"),
    "economic_score": ("E1", "E2", "E3"),
    "political_score": ("P1", "P2", "P3"),
    "social_cross_cutting_score": ("S1", "S2", "X1"),
}

TOP_N_PARTNERS = 15

# Former or combined economies and the successor codes that also appear in IMF
# IMTS. Used only to FLAG reporter-year-flows where both report positive values
# (the named-partner universe may then not be geographically disjoint). Values
# are never removed or redistributed.
HISTORICAL_SUCCESSORS = {
    "SUN": ("RUS", "UKR", "BLR", "MDA", "EST", "LVA", "LTU", "GEO", "ARM", "AZE", "KAZ", "KGZ", "TJK", "TKM", "UZB"),
    "YUG": ("SRB", "MNE", "HRV", "SVN", "BIH", "MKD", "KOS", "SCG"),
    "SCG": ("SRB", "MNE", "KOS"),
    "CSK": ("CZE", "SVK"),
    "DDR": ("DEU",),
    "ANT": ("CUW", "SXM", "BES", "CWX"),
    "CWX": ("CUW", "SXM"),
    "YAR": ("YEM",),
    "YMD": ("YEM",),
    "VDR": ("VNM",),
    "TX126": ("BEL", "LUX"),
    "TX554": ("MYS",),
}


def per_million(count, population_millions):
    """Rate per million residents. Nulls propagate; never coerced to zero."""
    if count is None or population_millions is None or population_millions <= 0:
        return None
    return count / population_millions


def fsum(values) -> float:
    """Correctly rounded float sum (math.fsum).

    Canonical arithmetic for every derived float: math.fsum is exactly rounded,
    so results do not depend on summation order, Python version or platform.
    Squares use x * x (IEEE exact rounding) rather than ** 2, which calls the
    platform libm pow() and differed in the last bit between Linux and macOS.
    """
    return math.fsum(values)


def hhi(values) -> float | None:
    """Herfindahl-Hirschman index (0-1) over a distribution of non-negative values."""
    vals = [v for v in values if v is not None and v > 0]
    total = fsum(vals)
    if total <= 0:
        return None
    return fsum((v / total) * (v / total) for v in vals)
