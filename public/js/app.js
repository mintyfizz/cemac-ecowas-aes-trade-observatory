/**
 * Dashboard state, API calls, and data-to-panel logic.
 */

"use strict";

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
  productsFlow: "export",
};

const METRIC_META = {
  total_trade: { label: "Total trade", format: shortMoneyB },
  trade_openness: { label: "Trade openness", format: value => fmtPct(value) },
  hhi: { label: "Partner HHI", format: value => fmtPlain(value, 3) },
  gdp: { label: "GDP", format: shortMoneyB },
  fragility: { label: "Fragility score", format: value => fmtPlain(value, 1) },
  conflict: { label: "Fatalities per million", format: value => fmtPlain(value, 1) },
};

async function fetchJSON(path) {
  const res = await fetch(API_BASE + path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

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

function deltaBadge(value, digits = 1, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  const tone = n > 0 ? "up" : n < 0 ? "down" : "flat";
  const arrow = n > 0 ? "▲" : n < 0 ? "▼" : "•";
  return `<span class="delta-badge ${tone}">${arrow} ${Math.abs(n).toFixed(digits)}${suffix}</span>`;
}

function metricDelta(current, previous, kind = "pct", digits = 1, suffix = "") {
  const curr = numberOrNull(current);
  const prev = numberOrNull(previous);
  if (curr == null || prev == null) return "";
  if (kind === "pct") {
    if (prev === 0) return "";
    return deltaBadge(((curr - prev) / Math.abs(prev)) * 100, digits, "% YoY");
  }
  if (kind === "pp") {
    return deltaBadge(curr - prev, digits, " pp YoY");
  }
  return deltaBadge(curr - prev, digits, `${suffix} YoY`);
}

function infoLine(deltaHtml, text) {
  const note = text ? `<span class="note-fragment">${escapeHTML(text)}</span>` : "";
  return `${deltaHtml || ""}${note}`;
}

function kpi(id, label, value, note, tone = "flat") {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("skeleton");
  el.innerHTML = `
    <div class="lbl">${escapeHTML(label)}</div>
    <div class="val">${escapeHTML(value)}</div>
    <div class="delta ${tone}">${note || ""}</div>
  `;
}

function econ(id, label, value, desc) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("skeleton");
  el.innerHTML = `
    <div class="lbl">${escapeHTML(label)}</div>
    <div class="val">${escapeHTML(value)}</div>
    <div class="desc">${desc || ""}</div>
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

function renderOverview(overview, previous = null) {
  const partner = overview.main_partner_iso3 || "--";
  const partnerName = overview.main_partner_name || partner;
  const conflict = overview.fatalities_per_million ?? overview.violent_events_per_million;
  const prevConflict = previous ? (previous.fatalities_per_million ?? previous.violent_events_per_million) : null;
  const partnerNote = previous?.main_partner_iso3 && previous.main_partner_iso3 !== partner
    ? infoLine("", `was ${previous.main_partner_iso3} in ${State.year - 1}`)
    : infoLine(metricDelta(overview.top_partner_share_pct, previous?.top_partner_share_pct, "pp", 1), `${partnerName} · ${fmtPct(overview.top_partner_share_pct)} of trade`);

  kpi("kpi-trade", "Total trade", shortMoneyB(overview.total_trade_billions_usd), infoLine(metricDelta(overview.total_trade_billions_usd, previous?.total_trade_billions_usd, "pct", 1), `USD billions, ${State.year}`));
  kpi("kpi-partner", "Main partner", partner, partnerNote);
  kpi("kpi-hhi", "Trade concentration", fmtPlain(overview.hhi, 3), infoLine(metricDelta(overview.hhi, previous?.hhi, "abs", 3), hhiBand(overview.hhi)));
  kpi("kpi-frag", "Fragility", fmtPlain(overview.avg_fsi_score, 1), fragBandPill(overview.fragility_band) + infoLine(metricDelta(overview.avg_fsi_score, previous?.avg_fsi_score, "abs", 1, " pts"), overview.fragility_band || "latest FSI where available"));
  kpi("kpi-conflict", "Conflict intensity", fmtPlain(conflict, 1), infoLine(metricDelta(conflict, prevConflict, "abs", 1, " /m"), overview.fatalities_per_million == null ? "violent events / million" : "fatalities / million"));
  kpi("kpi-open", "Trade openness", fmtPct(overview.trade_openness_pct_gdp), infoLine(metricDelta(overview.trade_openness_pct_gdp, previous?.trade_openness_pct_gdp, "pp", 1), "exports + imports / GDP"));

  econ("econ-gdp", "GDP", shortMoneyB(overview.gdp_current_usd_billions), infoLine(metricDelta(overview.gdp_current_usd_billions, previous?.gdp_current_usd_billions, "pct", 1), "current USD"));
  econ("econ-pop", "Population", fmtPop(overview.population_millions), infoLine(metricDelta(overview.population_millions, previous?.population_millions, "pct", 1), "millions"));
  econ("econ-gdp-pc", "GDP per capita", fmtCurrency(overview.gdp_per_capita_usd), infoLine(metricDelta(overview.gdp_per_capita_usd, previous?.gdp_per_capita_usd, "pct", 1), "USD, current"));
  econ("econ-growth", "Real GDP growth", fmtPct(overview.real_gdp_growth_pct), infoLine(metricDelta(overview.real_gdp_growth_pct, previous?.real_gdp_growth_pct, "pp", 1), "year-on-year"));
  econ("econ-inflation", "Inflation", fmtPct(overview.inflation_pct), infoLine(metricDelta(overview.inflation_pct, previous?.inflation_pct, "pp", 1), "avg consumer prices"));
  econ("econ-debt", "Govt debt / GDP", fmtPct(overview.govt_debt_pct_gdp), infoLine(metricDelta(overview.govt_debt_pct_gdp, previous?.govt_debt_pct_gdp, "pp", 1), "GDP-weighted for bloc views"));
  econ("econ-trade-gdp", "Fiscal balance", fmtPct(overview.fiscal_balance_pct_gdp), infoLine(metricDelta(overview.fiscal_balance_pct_gdp, previous?.fiscal_balance_pct_gdp, "pp", 1), "net lending / borrowing % GDP"));
  econ("econ-exports-gdp", "Exports / GDP", fmtPct(overview.exports_pct_gdp), infoLine(metricDelta(overview.exports_pct_gdp, previous?.exports_pct_gdp, "pp", 1), "export exposure"));
  econ("econ-imports-gdp", "Imports / GDP", fmtPct(overview.imports_pct_gdp), infoLine(metricDelta(overview.imports_pct_gdp, previous?.imports_pct_gdp, "pp", 1), "import reliance"));

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

function fragBandClass(band) {
  if (!band) return "band-unknown";
  const b = band.toLowerCase();
  if (b.includes("very high alert")) return "band-very-high-alert";
  if (b.includes("high alert")) return "band-high-alert";
  if (b.includes("alert")) return "band-alert";
  if (b.includes("elevated warning") || b.includes("high warning")) return "band-elevated-warning";
  if (b.includes("warning")) return "band-warning";
  return "band-stable";
}

function fragBandPill(band) {
  if (!band) return "";
  return `<span class="frag-band-pill ${fragBandClass(band)}">${escapeHTML(band)}</span>`;
}

function riskScores(o) {
  const debt = numberOrNull(o.govt_debt_pct_gdp);
  const fiscal = numberOrNull(o.fiscal_balance_pct_gdp);
  const inflation = numberOrNull(o.inflation_pct);
  const currentAccount = numberOrNull(o.current_account_pct_gdp);
  const fragility = numberOrNull(o.avg_fsi_score);
  const conflict = numberOrNull(o.fatalities_per_million);
  return [
    { label: "Debt burden", score: rangeScore(debt, 40, 100), actual: fmtPct(debt), detail: "gross government debt / GDP" },
    { label: "Fiscal deficit", score: rangeScore(fiscal == null ? null : -fiscal, 3, 10), actual: fmtPct(fiscal), detail: "net lending / borrowing, % GDP" },
    { label: "Inflation", score: rangeScore(inflation, 5, 25), actual: fmtPct(inflation), detail: "consumer prices, annual %" },
    { label: "External deficit", score: rangeScore(currentAccount == null ? null : -currentAccount, 3, 20), actual: fmtPct(currentAccount), detail: "current account balance / GDP" },
    { label: "Fragility", score: fragility == null ? null : clamp(fragility / 120 * 100), actual: fmtPlain(fragility, 1), detail: "Fund for Peace FSI, latest available" },
    { label: "Conflict", score: conflict == null ? null : clamp(conflict / 200 * 100), actual: `${fmtPlain(conflict, 1)} /m`, detail: "fatalities per million" },
  ];
}

function clamp(value) {
  return Math.max(0, Math.min(100, value));
}

function rangeScore(value, low, high) {
  const n = numberOrNull(value);
  if (n == null) return null;
  return clamp((n - low) / (high - low) * 100);
}

function setMapTitle() {
  const meta = METRIC_META[State.mapMetric] || METRIC_META.trade_openness;
  const mapTitle = document.getElementById("map-title");
  const mapSub = document.getElementById("map-sub");
  if (mapTitle) {
    mapTitle.textContent = `${State.country ? scopeName() : "All blocs"} · ${meta.label}`;
  }
  if (mapSub) {
    mapSub.textContent = State.country
      ? "Country selected - use Back to return to bloc view"
      : "Click a country to drill in";
  }
}

async function loadOverview(version) {
  const params = new URLSearchParams({
    bloc: State.bloc,
    year: State.year,
    ...(State.country ? { country: State.country } : {}),
  });
  const previousParams = new URLSearchParams({
    bloc: State.bloc,
    year: Math.max(1990, State.year - 1),
    ...(State.country ? { country: State.country } : {}),
  });
  const [overview, previous] = await Promise.all([
    fetchJSON(`/api/overview?${params}`),
    State.year > 1990 ? fetchJSON(`/api/overview?${previousParams}`) : Promise.resolve(null),
  ]);
  if (!isFresh(version)) return;
  renderOverview(overview, previous);
}

async function loadMap(version) {
  const params = new URLSearchParams({ metric: State.mapMetric, year: State.year });
  const rows = await fetchJSON(`/api/map?${params}`);
  if (!isFresh(version)) return;
  State.mapRows = rows;
  setMapTitle();
  await renderMap(rows, State, METRIC_META[State.mapMetric] || METRIC_META.trade_openness);
}

async function loadPartners(version) {
  const partnerTitle = document.getElementById("partners-title");
  const partnerSub = document.getElementById("partners-sub");
  const partnerBars = document.getElementById("partner-bars");
  if (partnerTitle) partnerTitle.textContent = `${scopeName()} · Top 10 trading partners`;
  if (partnerSub) partnerSub.textContent = `Trade value, USD billions · ${State.year} · ranked within selected scope`;
  if (partnerBars) partnerBars.innerHTML = `<div class="empty-state">Loading ${State.year} partner data...</div>`;

  const params = new URLSearchParams({
    bloc: State.bloc,
    year: State.year,
    ...(State.country ? { country: State.country } : {}),
  });
  const rows = await fetchJSON(`/api/partners?${params}`);
  if (!isFresh(version)) return;

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
  const params = new URLSearchParams({
    bloc: State.bloc,
    partner1: State.p1,
    partner2: State.p2,
    ...(State.country ? { country: State.country } : {}),
  });
  const rows = await fetchJSON(`/api/partner-history?${params}`);
  if (!isFresh(version)) return;
  renderPartnerTrend(rows, State.p1, State.p2);
}

async function loadConcentration(version) {
  const integrationTitle = document.getElementById("integration-title");
  if (integrationTitle) integrationTitle.textContent = "Trade openness trend (% of GDP)";
  const integrationSub = document.getElementById("integration-sub");
  if (integrationSub) {
    integrationSub.textContent = "Exports + imports as % of GDP — higher signals greater external trade dependency";
  }

  const params = new URLSearchParams({
    bloc: State.bloc,
    year: State.year,
    ...(State.country ? { country: State.country } : {}),
  });
  const data = await fetchJSON(`/api/concentration?${params}`);
  if (!isFresh(version)) return;
  document.getElementById("hhi-title").textContent = State.country ? `${scopeName()} · Partner concentration (HHI)` : "Partner concentration (HHI)";
  renderHHI(data, State);
  renderIntegration(data.intra || [], State);
}

async function loadGrowth(version) {
  const params = new URLSearchParams({
    bloc: State.bloc,
    ...(State.country ? { country: State.country } : {}),
  });
  const rows = await fetchJSON(`/api/growth?${params}`);
  if (!isFresh(version)) return;
  document.getElementById("growth-title").textContent = `${scopeName()} · Trade growth indexed to 1990`;
  document.getElementById("growth-sub").textContent = State.country
    ? "Selected country - 1990 = 100 - nominal current USD"
    : `${State.bloc} members - each country rebased to 1990 = 100`;
  document.getElementById("growth-note").textContent =
    "Source: IMF IMTS/DOTS · 1990 = 100 index · nominal current USD · missing years shown as gaps · log scale when range exceeds 15×";
  renderGrowth(rows, State);
}

async function loadOperational(version) {
  const params = new URLSearchParams({
    bloc: State.bloc,
    year: State.year,
    ...(State.country ? { country: State.country } : {}),
  });
  const data = await fetchJSON(`/api/operational?${params}`);
  if (!isFresh(version)) return;
  document.getElementById("conflict-title").textContent = State.country
    ? `${scopeName()} · Conflict hotspots`
    : `${scopeName()} · Conflict by country`;
  document.getElementById("conflict-sub").textContent = State.country
    ? "ACLED · admin1 regions, fatalities & violent events, latest 3-year hotspot window"
    : "ACLED · member countries, fatalities & violent events, latest 3-year window";
  renderConflict(data.conflict || []);
  renderFragility(data.fragility || []);
}

async function loadHealth(version) {
  const data = await fetchJSON("/api/health");
  if (!isFresh(version)) return;
  renderHealth(data.panels || []);
}

async function loadProducts(version) {
  const titleEl = document.getElementById("products-title");
  const subEl   = document.getElementById("products-sub");
  const noteEl  = document.getElementById("products-note");
  const emptyEl = document.getElementById("products-empty");
  const chartEl = document.getElementById("products-chart");
  if (titleEl) titleEl.textContent = `${scopeName()} · Top ${State.productsFlow} sectors`;
  if (subEl) subEl.textContent = `Loading ${State.productsFlow} product sectors...`;
  if (noteEl) noteEl.textContent = "";
  if (emptyEl) {
    emptyEl.hidden = true;
    emptyEl.textContent = "";
  }
  if (chartEl) chartEl.style.display = "";

  const params = new URLSearchParams({
    bloc: State.bloc,
    year: State.year,
    flow: State.productsFlow,
    ...(State.country ? { country: State.country } : {}),
  });
  const data = await fetchJSON(`/api/products?${params}`);
  if (!isFresh(version)) return;
  if (!data.available) {
    destroyChart("products-chart");
    if (chartEl) chartEl.style.display = "none";
    if (subEl) subEl.textContent = data.coverage_note || "Product data not available for this selection.";
    if (emptyEl) {
      emptyEl.hidden = false;
      emptyEl.textContent = data.latest_year
        ? `No selected-year HS2 product coverage. Latest available product year is ${data.latest_year}.`
        : "No HS2 product coverage is available for this selection.";
    }
    if (noteEl) noteEl.textContent = "";
    return;
  }
  if (chartEl) chartEl.style.display = "";
  if (emptyEl) emptyEl.hidden = true;
  if (subEl) subEl.textContent = data.coverage_note || `UN Comtrade · ${State.year}`;
  if (noteEl) noteEl.textContent = "Reporter-submitted UN Comtrade HS2 values. Shares are within the displayed flow and scope.";
  renderProducts(data.rows, State.productsFlow);
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
    loadProducts(version),
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

  document.getElementById("flow-toggle")?.addEventListener("click", event => {
    const btn = event.target.closest(".flow-btn");
    if (!btn) return;
    State.productsFlow = btn.dataset.flow;
    document.querySelectorAll(".flow-btn").forEach(b => b.classList.toggle("active", b === btn));
    loadProducts(State.loadVersion);
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
    State.meta = await fetchJSON("/api/meta");
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
