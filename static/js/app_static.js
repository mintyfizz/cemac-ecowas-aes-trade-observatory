/**
 * Static dashboard – GitHub Pages build.
 *
 * Identical rendering logic to app.js, but data comes from five pre-exported
 * JSON files in data/ instead of live FastAPI endpoints.  No server needed.
 *
 * Data files (written by scripts/export_static.py):
 *   data/country_timeseries.json
 *   data/top_trade_partners.json
 *   data/conflict_hotspots.json
 *   data/fragility_components.json
 *   data/bloc_comparison.json
 */

"use strict";

// ---------------------------------------------------------------------------
// Constants (mirror api/index.py)
// ---------------------------------------------------------------------------

const BLOCS = {
  CEMAC:  ["CMR", "CAF", "TCD", "COG", "GNQ", "GAB"],
  ECOWAS: ["BEN", "BFA", "CPV", "CIV", "GMB", "GHA", "GIN", "GNB",
           "LBR", "MLI", "NER", "NGA", "SEN", "SLE", "TGO"],
  AES:    ["MLI", "BFA", "NER"],
};

const COUNTRY_NAMES = {
  CMR: "Cameroon", CAF: "Central African Republic", TCD: "Chad",
  COG: "Congo", GNQ: "Equatorial Guinea", GAB: "Gabon",
  BEN: "Benin", BFA: "Burkina Faso", CPV: "Cabo Verde",
  CIV: "Côte d'Ivoire", GMB: "Gambia", GHA: "Ghana",
  GIN: "Guinea", GNB: "Guinea-Bissau", LBR: "Liberia",
  MLI: "Mali", NER: "Niger", NGA: "Nigeria",
  SEN: "Senegal", SLE: "Sierra Leone", TGO: "Togo",
};

const MAP_METRIC_COLS = {
  total_trade:    "total_trade_billions_usd",
  trade_openness: "trade_openness_pct_gdp",
  hhi:            "total_trade_partner_hhi",
  gdp:            "gdp_current_usd_billions",
  fragility:      "fsi_total_score",
  conflict:       "fatalities_per_million",
};

const ISO3_RE = /^[A-Z]{3}$/;

// ---------------------------------------------------------------------------
// In-memory database (populated at startup)
// ---------------------------------------------------------------------------

const DB = {
  timeseries: [],   // dashboard_country_timeseries
  partners:   [],   // dashboard_top_trade_partners
  conflict:   [],   // dashboard_conflict_hotspots
  fragility:  [],   // dashboard_fragility_components
  bloc:       [],   // dashboard_bloc_comparison
};

async function loadData() {
  const base = document.baseURI.replace(/[^/]*$/, "");
  [
    DB.timeseries,
    DB.partners,
    DB.conflict,
    DB.fragility,
    DB.bloc,
  ] = await Promise.all([
    fetch(base + "data/country_timeseries.json").then(r => r.json()),
    fetch(base + "data/top_trade_partners.json").then(r => r.json()),
    fetch(base + "data/conflict_hotspots.json").then(r => r.json()),
    fetch(base + "data/fragility_components.json").then(r => r.json()),
    fetch(base + "data/bloc_comparison.json").then(r => r.json()),
  ]);

  // Coerce numeric strings that Databricks may serialise as strings.
  for (const r of DB.timeseries) coerceNums(r);
  for (const r of DB.partners)   coerceNums(r);
  for (const r of DB.conflict)   coerceNums(r);
  for (const r of DB.fragility)  coerceNums(r);
  for (const r of DB.bloc)       coerceNums(r);
}

const NUM_KEYS = new Set([
  "year", "total_trade_billions_usd", "exports_billions_usd", "imports_billions_usd",
  "trade_balance_billions_usd", "trade_openness_pct_gdp", "exports_pct_gdp", "imports_pct_gdp",
  "gdp_current_usd_billions", "gdp_per_capita_current_usd", "population_millions",
  "real_gdp_growth_pct_imf", "inflation_cpi_pct", "gross_debt_pct_gdp_imf",
  "net_lending_borrowing_pct_gdp_imf", "current_account_balance_pct_gdp_imf",
  "total_trade_partner_hhi", "violent_events", "fatalities",
  "violent_events_per_million", "fatalities_per_million", "fsi_total_score",
  "total_trade_partner_share_pct", "partner_rank", "hotspot_rank",
  "fsi_year", "window_start_year", "window_end_year",
  "cohesion_score", "economic_score", "political_score", "social_cross_cutting_score",
  "share_pct", "index_value",
]);

function coerceNums(row) {
  for (const key of Object.keys(row)) {
    if (NUM_KEYS.has(key) && row[key] !== null && row[key] !== undefined) {
      const n = Number(row[key]);
      row[key] = Number.isFinite(n) ? n : null;
    }
  }
}

// ---------------------------------------------------------------------------
// Local query helpers (JavaScript implementations of the FastAPI endpoints)
// ---------------------------------------------------------------------------

function localMeta() {
  return {
    blocs: BLOCS,
    country_names: COUNTRY_NAMES,
    years: Array.from({ length: 35 }, (_, i) => 2024 - i),
    map_metrics: [
      { value: "trade_openness", label: "Trade openness (% GDP)" },
      { value: "hhi",            label: "Partner concentration (HHI)" },
      { value: "total_trade",    label: "Total trade (USD B)" },
      { value: "gdp",            label: "GDP (USD B)" },
      { value: "fragility",      label: "Fragility score" },
      { value: "conflict",       label: "Fatalities per million" },
    ],
  };
}

// /api/map?metric=M&year=Y
function localMap(metric, year) {
  const col = MAP_METRIC_COLS[metric] || "trade_openness_pct_gdp";
  return DB.timeseries
    .filter(r => r.year === year)
    .map(r => ({
      country_iso3: r.country_iso3,
      country_name: r.country_name,
      analytical_bloc_code: r.analytical_bloc_code,
      value: r[col] ?? null,
    }));
}

// /api/overview?bloc=B&year=Y[&country=C]
function localOverview(bloc, year, country) {
  if (country) {
    const b = DB.timeseries.find(r => r.country_iso3 === country && r.year === year) || {};
    const validPartners = DB.partners
      .filter(r => r.country_iso3 === country && r.year === year && ISO3_RE.test(r.counterpart_iso3))
      .sort((a, z) => (a.partner_rank ?? 999) - (z.partner_rank ?? 999));
    const top = validPartners[0] || {};
    const latestFsi = DB.fragility.find(r => r.country_iso3 === country) || {};
    const gdp = b.gdp_current_usd_billions || null;
    return {
      total_trade_billions_usd: b.total_trade_billions_usd ?? null,
      exports_billions_usd: b.exports_billions_usd ?? null,
      imports_billions_usd: b.imports_billions_usd ?? null,
      hhi: b.total_trade_partner_hhi ?? null,
      main_partner_iso3: top.counterpart_iso3 ?? null,
      main_partner_name: top.counterpart_name ?? null,
      main_partner_trade_billions_usd: top.total_trade_billions_usd ?? null,
      top_partner_share_pct: (top.total_trade_billions_usd != null && b.total_trade_billions_usd)
        ? top.total_trade_billions_usd / b.total_trade_billions_usd * 100 : null,
      gdp_current_usd_billions: gdp,
      gdp_per_capita_usd: b.gdp_per_capita_current_usd ?? null,
      population_millions: b.population_millions ?? null,
      real_gdp_growth_pct: b.real_gdp_growth_pct_imf ?? null,
      inflation_pct: b.inflation_cpi_pct ?? null,
      govt_debt_pct_gdp: b.gross_debt_pct_gdp_imf ?? null,
      fiscal_balance_pct_gdp: b.net_lending_borrowing_pct_gdp_imf ?? null,
      current_account_pct_gdp: b.current_account_balance_pct_gdp_imf ?? null,
      trade_balance_billions_usd: b.trade_balance_billions_usd ?? null,
      violent_events_per_million: b.violent_events_per_million ?? null,
      fatalities_per_million: b.fatalities_per_million ?? null,
      fatalities: b.fatalities ?? null,
      violent_events: b.violent_events ?? null,
      fragility_band: b.fragility_band ?? null,
      avg_fsi_score: b.fsi_total_score ?? latestFsi.fsi_total_score ?? null,
      trade_openness_pct_gdp: b.trade_openness_pct_gdp ?? null,
      exports_pct_gdp: (b.exports_billions_usd != null && gdp) ? b.exports_billions_usd / gdp * 100 : null,
      imports_pct_gdp: (b.imports_billions_usd != null && gdp) ? b.imports_billions_usd / gdp * 100 : null,
      year: b.year ?? year,
    };
  }

  // Bloc-level aggregate
  const scoped = DB.timeseries.filter(r => r.analytical_bloc_code === bloc && r.year === year);
  const fsiMap = Object.fromEntries(DB.fragility.map(r => [r.country_iso3, r.fsi_total_score]));

  const sum = col => scoped.reduce((acc, r) => acc + (r[col] ?? 0), 0);

  function weightedAvg(col, wCol) {
    let num = 0, den = 0;
    for (const r of scoped) {
      if (r[col] != null && r[wCol] != null) { num += r[col] * r[wCol]; den += r[wCol]; }
    }
    return den > 0 ? num / den : null;
  }

  const validPartners = DB.partners.filter(
    r => r.analytical_bloc_code === bloc && r.year === year && ISO3_RE.test(r.counterpart_iso3),
  );
  const partnerAgg = {};
  for (const r of validPartners) {
    if (!partnerAgg[r.counterpart_iso3]) {
      partnerAgg[r.counterpart_iso3] = { iso3: r.counterpart_iso3, name: r.counterpart_name, total: 0 };
    }
    partnerAgg[r.counterpart_iso3].total += r.total_trade_billions_usd ?? 0;
  }
  const top = Object.values(partnerAgg).sort((a, z) => z.total - a.total)[0] || {};

  const totalTrade = sum("total_trade_billions_usd");
  const totalGdp   = sum("gdp_current_usd_billions");
  const totalPop   = sum("population_millions");
  const totalVE    = sum("violent_events");
  const totalFat   = sum("fatalities");

  let fsiSum = 0, fsiCount = 0;
  for (const r of scoped) {
    const v = r.fsi_total_score ?? fsiMap[r.country_iso3];
    if (v != null) { fsiSum += v; fsiCount++; }
  }

  return {
    total_trade_billions_usd: totalTrade,
    exports_billions_usd: sum("exports_billions_usd"),
    imports_billions_usd: sum("imports_billions_usd"),
    hhi: weightedAvg("total_trade_partner_hhi", "total_trade_billions_usd"),
    main_partner_iso3: top.iso3 ?? null,
    main_partner_name: top.name ?? null,
    main_partner_trade_billions_usd: top.total ?? null,
    top_partner_share_pct: (top.total && totalTrade) ? top.total / totalTrade * 100 : null,
    gdp_current_usd_billions: totalGdp,
    population_millions: totalPop,
    gdp_per_capita_usd: totalPop ? totalGdp / totalPop * 1000 : null,
    real_gdp_growth_pct: weightedAvg("real_gdp_growth_pct_imf", "gdp_current_usd_billions"),
    inflation_pct: weightedAvg("inflation_cpi_pct", "gdp_current_usd_billions"),
    govt_debt_pct_gdp: weightedAvg("gross_debt_pct_gdp_imf", "gdp_current_usd_billions"),
    fiscal_balance_pct_gdp: weightedAvg("net_lending_borrowing_pct_gdp_imf", "gdp_current_usd_billions"),
    current_account_pct_gdp: weightedAvg("current_account_balance_pct_gdp_imf", "gdp_current_usd_billions"),
    trade_balance_billions_usd: sum("trade_balance_billions_usd"),
    violent_events: totalVE,
    fatalities: totalFat,
    violent_events_per_million: totalPop ? totalVE / totalPop : null,
    fatalities_per_million: totalPop ? totalFat / totalPop : null,
    fragility_band: null,
    avg_fsi_score: fsiCount ? fsiSum / fsiCount : null,
    trade_openness_pct_gdp: totalGdp ? totalTrade / totalGdp * 100 : null,
    exports_pct_gdp: totalGdp ? sum("exports_billions_usd") / totalGdp * 100 : null,
    imports_pct_gdp: totalGdp ? sum("imports_billions_usd") / totalGdp * 100 : null,
    year,
  };
}

// /api/partners?bloc=B&year=Y[&country=C]
function localPartners(bloc, year, country) {
  if (country) {
    return DB.partners
      .filter(r => r.country_iso3 === country && r.year === year && ISO3_RE.test(r.counterpart_iso3))
      .sort((a, z) => (a.partner_rank ?? 999) - (z.partner_rank ?? 999))
      .slice(0, 10)
      .map(r => ({
        counterpart_iso3: r.counterpart_iso3,
        counterpart_name: r.counterpart_name,
        exports_billions_usd: r.exports_billions_usd,
        imports_billions_usd: r.imports_billions_usd,
        total_trade_billions_usd: r.total_trade_billions_usd,
        total_trade_partner_share_pct: r.total_trade_partner_share_pct,
        partner_rank: r.partner_rank,
      }));
  }

  const valid = DB.partners.filter(
    r => r.analytical_bloc_code === bloc && r.year === year && ISO3_RE.test(r.counterpart_iso3),
  );
  const agg = {};
  for (const r of valid) {
    if (!agg[r.counterpart_iso3]) {
      agg[r.counterpart_iso3] = {
        counterpart_iso3: r.counterpart_iso3,
        counterpart_name: r.counterpart_name,
        exports_billions_usd: 0,
        imports_billions_usd: 0,
        total_trade_billions_usd: 0,
      };
    }
    const a = agg[r.counterpart_iso3];
    a.exports_billions_usd += r.exports_billions_usd ?? 0;
    a.imports_billions_usd += r.imports_billions_usd ?? 0;
    a.total_trade_billions_usd += r.total_trade_billions_usd ?? 0;
  }
  const rows = Object.values(agg).sort((a, z) => z.total_trade_billions_usd - a.total_trade_billions_usd);
  // Use the timeseries total (all bilateral flows) so shares aren't inflated by
  // the ISO3-only subset of the top-trade-partners table.
  const blocTotal = DB.timeseries
    .filter(r => r.analytical_bloc_code === bloc && r.year === year)
    .reduce((s, r) => s + (r.total_trade_billions_usd ?? 0), 0);
  return rows.slice(0, 10).map((r, i) => ({
    ...r,
    total_trade_partner_share_pct: blocTotal ? r.total_trade_billions_usd / blocTotal * 100 : null,
    partner_rank: i + 1,
  }));
}

// /api/partner-history?bloc=B&partner1=P1&partner2=P2[&country=C]
function localPartnerHistory(bloc, partner1, partner2, country) {
  const targets = new Set([partner1, partner2]);

  if (country) {
    return DB.partners
      .filter(r => r.country_iso3 === country && targets.has(r.counterpart_iso3) && ISO3_RE.test(r.counterpart_iso3))
      .sort((a, z) => a.year - z.year)
      .map(r => ({ year: r.year, counterpart_iso3: r.counterpart_iso3, share_pct: r.total_trade_partner_share_pct }));
  }

  const valid = DB.partners.filter(
    r => r.analytical_bloc_code === bloc && ISO3_RE.test(r.counterpart_iso3),
  );
  // Year totals from the country timeseries (includes all bilateral flows,
  // not just the top-15 ISO3 partners) so shares are correctly denominated.
  const yearTotals = {};
  for (const r of DB.timeseries) {
    if (r.analytical_bloc_code === bloc && r.total_trade_billions_usd != null) {
      yearTotals[r.year] = (yearTotals[r.year] ?? 0) + r.total_trade_billions_usd;
    }
  }
  // Selected partner totals by year
  const selected = valid.filter(r => targets.has(r.counterpart_iso3));
  const partnerYearAgg = {};
  for (const r of selected) {
    const key = `${r.year}__${r.counterpart_iso3}`;
    if (!partnerYearAgg[key]) partnerYearAgg[key] = { year: r.year, counterpart_iso3: r.counterpart_iso3, total: 0 };
    partnerYearAgg[key].total += r.total_trade_billions_usd ?? 0;
  }
  return Object.values(partnerYearAgg)
    .sort((a, z) => a.year - z.year)
    .map(r => ({
      year: r.year,
      counterpart_iso3: r.counterpart_iso3,
      share_pct: yearTotals[r.year] ? r.total / yearTotals[r.year] * 100 : null,
    }));
}

// /api/concentration?bloc=B&year=Y[&country=C]
function localConcentration(bloc, year, country) {
  let hhi;
  if (country) {
    hhi = DB.timeseries
      .filter(r => r.analytical_bloc_code === bloc && r.year === year)
      .sort((a, z) => (z.total_trade_partner_hhi ?? -1) - (a.total_trade_partner_hhi ?? -1))
      .map(r => ({
        country_iso3: r.country_iso3,
        country_name: r.country_name,
        analytical_bloc_code: r.analytical_bloc_code,
        hhi: r.total_trade_partner_hhi,
        year: r.year,
      }));
  } else {
    // Trade-weighted HHI per year per bloc
    const byYearBloc = {};
    for (const r of DB.timeseries) {
      const key = `${r.year}__${r.analytical_bloc_code}`;
      if (!byYearBloc[key]) byYearBloc[key] = { year: r.year, analytical_bloc_code: r.analytical_bloc_code, num: 0, den: 0 };
      if (r.total_trade_partner_hhi != null && r.total_trade_billions_usd != null) {
        byYearBloc[key].num += r.total_trade_partner_hhi * r.total_trade_billions_usd;
        byYearBloc[key].den += r.total_trade_billions_usd;
      }
    }
    hhi = Object.values(byYearBloc)
      .sort((a, z) => a.year - z.year)
      .map(r => ({ year: r.year, analytical_bloc_code: r.analytical_bloc_code, hhi: r.den ? r.num / r.den : null }));
  }

  const intra = DB.bloc
    .sort((a, z) => a.year - z.year)
    .map(r => ({ year: r.year, analytical_bloc_code: r.analytical_bloc_code, intra_share_pct: r.trade_openness_pct_gdp }));

  return { hhi, intra };
}

// /api/growth?bloc=B[&country=C]
function localGrowth(bloc, country) {
  let scoped;
  if (country) {
    scoped = DB.timeseries.filter(r => r.country_iso3 === country);
  } else {
    const members = new Set(BLOCS[bloc] || []);
    scoped = DB.timeseries.filter(r => members.has(r.country_iso3));
  }

  const base1990 = {};
  for (const r of scoped) {
    if (r.year === 1990 && r.total_trade_billions_usd > 0) {
      base1990[r.country_iso3] = r.total_trade_billions_usd;
    }
  }

  return scoped
    .sort((a, z) => a.year - z.year)
    .map(r => ({
      country_iso3: r.country_iso3,
      country_name: r.country_name,
      analytical_bloc_code: country ? r.analytical_bloc_code : bloc,
      year: r.year,
      base_year: 1990,
      base_trade_billions_usd: base1990[r.country_iso3] ?? null,
      total_trade_billions_usd: r.total_trade_billions_usd,
      index_value: base1990[r.country_iso3] && r.total_trade_billions_usd != null
        ? r.total_trade_billions_usd / base1990[r.country_iso3] * 100
        : null,
    }));
}

// /api/operational?bloc=B&year=Y[&country=C]
function localOperational(bloc, year, country) {
  const isCountry = !!country;
  const conflict = isCountry
    ? DB.conflict
        .filter(r => r.country_iso3 === country)
        .sort((a, z) => (a.hotspot_rank ?? 999) - (z.hotspot_rank ?? 999))
        .map(r => ({
          country_iso3: r.country_iso3,
          country_name: r.country_name,
          analytical_bloc_code: r.analytical_bloc_code,
          admin1: r.admin1,
          window_start_year: r.window_start_year,
          window_end_year: r.window_end_year,
          violent_events: r.violent_events,
          fatalities: r.fatalities,
          fatalities_per_million: r.fatalities_per_million,
        }))
    : Object.values(DB.conflict
        .filter(r => r.analytical_bloc_code === bloc)
        .reduce((acc, r) => {
          const key = r.country_iso3;
          if (!acc[key]) {
            acc[key] = {
              country_iso3: r.country_iso3,
              country_name: r.country_name,
              analytical_bloc_code: r.analytical_bloc_code,
              admin1: null,
              window_start_year: r.window_start_year,
              window_end_year: r.window_end_year,
              violent_events: 0,
              fatalities: 0,
              fatalities_per_million: null,
            };
          }
          acc[key].window_start_year = Math.min(acc[key].window_start_year ?? r.window_start_year, r.window_start_year ?? acc[key].window_start_year);
          acc[key].window_end_year = Math.max(acc[key].window_end_year ?? r.window_end_year, r.window_end_year ?? acc[key].window_end_year);
          acc[key].violent_events += r.violent_events ?? 0;
          acc[key].fatalities += r.fatalities ?? 0;
          return acc;
        }, {}))
        .sort((a, z) => (z.violent_events ?? 0) - (a.violent_events ?? 0) || (z.fatalities ?? 0) - (a.fatalities ?? 0) || a.country_name.localeCompare(z.country_name));

  const fragility = DB.fragility
    .filter(r => isCountry ? r.country_iso3 === country : r.analytical_bloc_code === bloc)
    .sort((a, z) => (z.fsi_total_score ?? 0) - (a.fsi_total_score ?? 0))
    .map(r => ({
      country_iso3: r.country_iso3,
      country_name: r.country_name,
      analytical_bloc_code: r.analytical_bloc_code,
      fsi_total_score: r.fsi_total_score,
      cohesion_score: r.cohesion_score,
      economic_score: r.economic_score,
      political_score: r.political_score,
      social_cross_cutting_score: r.social_cross_cutting_score,
      fsi_year: r.fsi_year,
    }));

  return { conflict, fragility };
}

// /api/health  (computed from in-memory data)
function localHealthData() {
  const ts = DB.timeseries;
  const countries = new Set(ts.map(r => r.country_iso3)).size;
  const years = ts.map(r => r.year);
  const minYear = Math.min(...years);
  const maxYear = Math.max(...years);

  const blocs = new Set(DB.bloc.map(r => r.analytical_bloc_code)).size;

  const totalVE  = DB.conflict.reduce((s, r) => s + (r.violent_events ?? 0), 0);
  const totalFat = DB.conflict.reduce((s, r) => s + (r.fatalities ?? 0), 0);
  const cYears   = DB.conflict.map(r => r.window_start_year).filter(Boolean);
  const cMaxYears = DB.conflict.map(r => r.window_end_year).filter(Boolean);

  const fsiYears = DB.fragility.map(r => r.fsi_year).filter(Boolean);

  return {
    status: "ok",
    panels: [
      {
        label: "Country-year mart",
        value: `${ts.length} rows`,
        description: `${countries} countries · ${minYear}-${maxYear}`,
      },
      {
        label: "Bloc mart",
        value: `${blocs} blocs`,
        description: `${DB.bloc.length} bloc-year rows`,
      },
      {
        label: "ACLED coverage",
        value: `${totalVE.toLocaleString("en-US")} events`,
        description: cYears.length
          ? `hotspot windows cover ${Math.min(...cYears)}-${Math.max(...cMaxYears)}`
          : "no conflict data",
      },
      {
        label: "FSI coverage",
        value: `${DB.fragility.length} countries`,
        description: fsiYears.length
          ? `latest components from ${Math.min(...fsiYears)}-${Math.max(...fsiYears)}; no 2024 release in source`
          : "no FSI data",
      },
    ],
  };
}

// ---------------------------------------------------------------------------
// Dashboard state
// ---------------------------------------------------------------------------

const API_BASE = "";

const State = {
  bloc: "CEMAC",
  year: 2024,
  country: null,
  mapMetric: "trade_openness",
  p1: null,
  p2: null,
  meta: null,
  mapRows: [],
  loadVersion: 0,
};

const METRIC_META = {
  total_trade:    { label: "Total trade", format: shortMoneyB },
  trade_openness: { label: "Trade openness", format: value => fmtPct(value) },
  hhi:            { label: "Partner HHI", format: value => fmtPlain(value, 3) },
  gdp:            { label: "GDP", format: shortMoneyB },
  fragility:      { label: "Fragility score", format: value => fmtPlain(value, 1) },
  conflict:       { label: "Fatalities per million", format: value => fmtPlain(value, 1) },
};

function toast(message, duration = 6000) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("visible");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => el.classList.remove("visible"), duration);
}

function isFresh(version) {
  return version === State.loadVersion;
}

function countryName(iso) {
  return State.meta?.country_names?.[iso] || iso;
}

function scopeName() {
  return State.country ? countryName(State.country) : State.bloc;
}

function numberOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fmtCurrency(value, digits = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: digits })}`;
}

function fmtPop(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  if (n >= 1000) return `${(n / 1000).toFixed(2)}B`;
  return `${n.toFixed(n >= 10 ? 1 : 2)}M`;
}

function kpi(id, label, value, note, tone = "flat") {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("skeleton");
  el.innerHTML = `
    <div class="lbl">${escapeHTML(label)}</div>
    <div class="val">${escapeHTML(value)}</div>
    <div class="delta ${tone}">${escapeHTML(note || "")}</div>
  `;
}

function econ(id, label, value, desc) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("skeleton");
  el.innerHTML = `
    <div class="lbl">${escapeHTML(label)}</div>
    <div class="val">${escapeHTML(value)}</div>
    <div class="desc">${escapeHTML(desc || "")}</div>
  `;
}

function updateToolbarActive() {
  document.querySelectorAll(".bloc-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.bloc === State.bloc);
  });
}

function updateCrumb() {
  const el = document.getElementById("crumb");
  if (!el) return;
  if (State.country) {
    el.innerHTML =
      `Viewing <b>${escapeHTML(State.bloc)} - ${escapeHTML(scopeName())}</b>` +
      ` <span class="crumb-sep">·</span> <b>${State.year}</b>` +
      ` <span class="crumb-sep">·</span> country profile` +
      ` <button class="back-btn" id="back-btn" type="button">Back to ${escapeHTML(State.bloc)}</button>`;
    document.getElementById("back-btn")?.addEventListener("click", () => {
      State.country = null;
      State.p1 = null;
      State.p2 = null;
      loadAll();
    });
  } else {
    el.innerHTML =
      `Viewing <b>${escapeHTML(State.bloc)}</b>` +
      ` <span class="crumb-sep">·</span> <b>${State.year}</b>` +
      ` <span class="crumb-sep">·</span> all countries`;
  }
}

function renderOverview(overview) {
  const partner = overview.main_partner_iso3 || "--";
  const partnerName = overview.main_partner_name || partner;
  const conflict = overview.fatalities_per_million ?? overview.violent_events_per_million;

  kpi("kpi-trade", "Total trade", shortMoneyB(overview.total_trade_billions_usd), `USD billions, ${State.year}`);
  kpi("kpi-partner", "Main partner", partner, `${partnerName} · ${fmtPct(overview.top_partner_share_pct)} of trade`);
  kpi("kpi-hhi", "Partner HHI", fmtPlain(overview.hhi, 3), hhiBand(overview.hhi));
  kpi("kpi-frag", "Fragility", fmtPlain(overview.avg_fsi_score, 1), overview.fragility_band || "latest FSI where available");
  kpi("kpi-conflict", "Conflict intensity", fmtPlain(conflict, 1), overview.fatalities_per_million == null ? "violent events / million" : "fatalities / million");
  kpi("kpi-open", "Trade openness", fmtPct(overview.trade_openness_pct_gdp), "exports + imports / GDP");

  econ("econ-gdp", "GDP", shortMoneyB(overview.gdp_current_usd_billions), "current USD");
  econ("econ-pop", "Population", fmtPop(overview.population_millions), "millions");
  econ("econ-gdp-pc", "GDP per capita", fmtCurrency(overview.gdp_per_capita_usd), "USD, current");
  econ("econ-growth", "Real GDP growth", fmtPct(overview.real_gdp_growth_pct), "year-on-year");
  econ("econ-inflation", "Inflation", fmtPct(overview.inflation_pct), "avg consumer prices");
  econ("econ-debt", "Govt debt / GDP", fmtPct(overview.govt_debt_pct_gdp), "GDP-weighted for bloc views");
  econ("econ-trade-gdp", "Trade / GDP", fmtPct(overview.trade_openness_pct_gdp), "exports + imports");
  econ("econ-exports-gdp", "Exports / GDP", fmtPct(overview.exports_pct_gdp), "export exposure");
  econ("econ-imports-gdp", "Imports / GDP", fmtPct(overview.imports_pct_gdp), "import reliance");

  const note = document.getElementById("econ-note");
  if (note) {
    note.classList.remove("skeleton");
    note.innerHTML = `
      <div class="lbl">Economic context · ${escapeHTML(scopeName())}</div>
      <div class="desc">${escapeHTML(overview.economic_note || "IMF WEO metrics are shown with latest available values; bloc ratios use aggregate or weighted calculations.")}</div>
    `;
  }

  renderStructureTree(overview);
  renderRiskRadar(riskScores(overview), scopeName());
}

function hhiBand(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "no concentration score";
  if (n < 0.15) return "diversified partner base";
  if (n <= 0.25) return "moderately concentrated";
  return "highly concentrated";
}

function riskScores(o) {
  const debt    = clamp((numberOrNull(o.govt_debt_pct_gdp) || 0) / 100 * 100);
  const infl    = clamp((numberOrNull(o.inflation_pct) || 0) / 25 * 100);
  const ca      = clamp(Math.abs(numberOrNull(o.current_account_pct_gdp) || 0) / 20 * 100);
  const hhi     = clamp((numberOrNull(o.hhi) || 0) / 0.35 * 100);
  const frag    = clamp((numberOrNull(o.avg_fsi_score) || 0) / 120 * 100);
  const conflict = clamp((numberOrNull(o.fatalities_per_million) || 0) / 200 * 100);
  return { Debt: debt, Inflation: infl, "CA pressure": ca, "Partner HHI": hhi, Fragility: frag, Conflict: conflict };
}

function clamp(value) {
  return Math.max(0, Math.min(100, value));
}

function setMapTitle() {
  const meta = METRIC_META[State.mapMetric] || METRIC_META.trade_openness;
  const mapTitle = document.getElementById("map-title");
  const mapSub   = document.getElementById("map-sub");
  if (mapTitle) mapTitle.textContent = `${State.country ? scopeName() : "All blocs"} · ${meta.label}`;
  if (mapSub)   mapSub.textContent = State.country ? "Country selected - use Back to return to bloc view" : "Click a country to drill in";
}

// ---------------------------------------------------------------------------
// Load / render functions  (same signatures as app.js, but use local queries)
// ---------------------------------------------------------------------------

async function loadOverview(version) {
  const overview = localOverview(State.bloc, State.year, State.country);
  if (!isFresh(version)) return;
  renderOverview(overview);
}

async function loadMap(version) {
  const rows = localMap(State.mapMetric, State.year);
  if (!isFresh(version)) return;
  State.mapRows = rows;
  setMapTitle();
  await renderMap(rows, State, METRIC_META[State.mapMetric] || METRIC_META.trade_openness);
}

async function loadPartners(version) {
  const rows = localPartners(State.bloc, State.year, State.country);
  if (!isFresh(version)) return;

  document.getElementById("partners-title").textContent = `${scopeName()} · Top 10 trading partners`;
  document.getElementById("partners-sub").textContent = `Trade value, USD billions · ${State.year}`;
  renderPartnerBars(rows);

  const p1El = document.getElementById("p1-select");
  const p2El = document.getElementById("p2-select");
  const options = rows.map(row => `<option value="${escapeHTML(row.counterpart_iso3)}">${escapeHTML(row.counterpart_iso3)}</option>`).join("");
  p1El.innerHTML = options;
  p2El.innerHTML = options;

  if (!State.p1 || !rows.some(row => row.counterpart_iso3 === State.p1)) State.p1 = rows[0]?.counterpart_iso3 || null;
  if (!State.p2 || !rows.some(row => row.counterpart_iso3 === State.p2)) State.p2 = rows[1]?.counterpart_iso3 || State.p1;
  if (State.p1) p1El.value = State.p1;
  if (State.p2) p2El.value = State.p2;

  await loadPartnerTrend(version);
}

async function loadPartnerTrend(version = State.loadVersion) {
  if (!State.p1 || !State.p2) return;
  const rows = localPartnerHistory(State.bloc, State.p1, State.p2, State.country);
  if (!isFresh(version)) return;
  renderPartnerTrend(rows, State.p1, State.p2);
}

async function loadConcentration(version) {
  const data = localConcentration(State.bloc, State.year, State.country);
  if (!isFresh(version)) return;
  document.getElementById("hhi-title").textContent = State.country ? `${scopeName()} · HHI vs peers` : "Partner concentration (HHI)";
  renderHHI(data, State);
  renderIntegration(data.intra || [], State);
}

async function loadGrowth(version) {
  const rows = localGrowth(State.bloc, State.country);
  if (!isFresh(version)) return;
  document.getElementById("growth-title").textContent = `${scopeName()} · Trade growth indexed to 1990`;
  document.getElementById("growth-sub").textContent = State.country
    ? "Selected country - 1990 = 100 - nominal current USD"
    : `${State.bloc} members - each country rebased to 1990 = 100`;
  document.getElementById("growth-note").textContent =
    "Index = total goods trade (exports + imports) / 1990 total goods trade * 100. Log scale is used when outliers would flatten the comparison.";
  renderGrowth(rows, State);
}

async function loadOperational(version) {
  const data = localOperational(State.bloc, State.year, State.country);
  if (!isFresh(version)) return;
  document.getElementById("conflict-title").textContent = State.country
    ? `${scopeName()} · Conflict hotspots`
    : `${scopeName()} · Conflict by country`;
  document.getElementById("conflict-sub").textContent = State.country
    ? "ACLED - admin1 regions, latest 3-year hotspot window"
    : "ACLED - member countries, latest 3-year window";
  renderConflict(data.conflict || []);
  renderFragility(data.fragility || []);
}

async function loadHealth(version) {
  const data = localHealthData();
  if (!isFresh(version)) return;
  renderHealth(data.panels || []);
}

async function loadAll() {
  const version = ++State.loadVersion;
  updateToolbarActive();
  updateCrumb();
  setMapTitle();

  const results = await Promise.allSettled([
    loadOverview(version),
    loadMap(version),
    loadPartners(version),
    loadConcentration(version),
    loadGrowth(version),
    loadOperational(version),
    loadHealth(version),
  ]);
  const failed = results.find(r => r.status === "rejected");
  if (failed && isFresh(version)) {
    console.error(failed.reason);
    toast(`Dashboard data error: ${failed.reason.message}`);
  }
}

function populateYears(years) {
  const el = document.getElementById("year-select");
  const sorted = [...years].sort((a, b) => b - a);
  el.innerHTML = sorted.map(year => `<option value="${year}">${year}</option>`).join("");
  el.value = State.year;
}

function populateMetrics(metrics) {
  const el = document.getElementById("metric-select");
  el.innerHTML = metrics.map(metric => `<option value="${escapeHTML(metric.value)}">${escapeHTML(metric.label)}</option>`).join("");
  el.value = State.mapMetric;
}

function attachListeners() {
  document.getElementById("bloc-tabs").addEventListener("click", event => {
    const button = event.target.closest(".bloc-btn");
    if (!button) return;
    State.bloc = button.dataset.bloc;
    State.country = null;
    State.p1 = null;
    State.p2 = null;
    loadAll();
  });

  document.getElementById("year-select").addEventListener("change", event => {
    State.year = parseInt(event.target.value, 10);
    loadAll();
  });

  document.getElementById("metric-select").addEventListener("change", event => {
    State.mapMetric = event.target.value;
    loadMap(++State.loadVersion);
  });

  document.getElementById("p1-select").addEventListener("change", event => {
    State.p1 = event.target.value;
    loadPartnerTrend();
  });

  document.getElementById("p2-select").addEventListener("change", event => {
    State.p2 = event.target.value;
    loadPartnerTrend();
  });
}

window.dashboardSelectCountry = function dashboardSelectCountry(iso) {
  const row = State.mapRows.find(item => item.country_iso3 === iso);
  State.country = iso;
  if (row?.analytical_bloc_code) State.bloc = row.analytical_bloc_code;
  State.p1 = null;
  State.p2 = null;
  loadAll();
};

async function init() {
  try {
    await loadData();
    State.meta = localMeta();
    populateYears(State.meta.years || [2024]);
    populateMetrics(State.meta.map_metrics || []);
    attachListeners();
    await loadAll();
  } catch (error) {
    console.error(error);
    toast(`Could not initialize dashboard: ${error.message}`, 10000);
  }
}

document.addEventListener("DOMContentLoaded", init);
