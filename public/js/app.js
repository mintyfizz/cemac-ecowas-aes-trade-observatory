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
  const debt = clamp((numberOrNull(o.govt_debt_pct_gdp) || 0) / 100 * 100);
  const infl = clamp((numberOrNull(o.inflation_pct) || 0) / 25 * 100);
  const ca = clamp(Math.abs(numberOrNull(o.current_account_pct_gdp) || 0) / 20 * 100);
  const hhi = clamp((numberOrNull(o.hhi) || 0) / 0.35 * 100);
  const frag = clamp((numberOrNull(o.avg_fsi_score) || 0) / 120 * 100);
  const conflict = clamp((numberOrNull(o.fatalities_per_million) || 0) / 200 * 100);
  return {
    Debt: debt,
    Inflation: infl,
    "CA pressure": ca,
    "Partner HHI": hhi,
    Fragility: frag,
    Conflict: conflict,
  };
}

function clamp(value) {
  return Math.max(0, Math.min(100, value));
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
  const overview = await fetchJSON(`/api/overview?${params}`);
  if (!isFresh(version)) return;
  renderOverview(overview);
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
  const params = new URLSearchParams({
    bloc: State.bloc,
    year: State.year,
    ...(State.country ? { country: State.country } : {}),
  });
  const rows = await fetchJSON(`/api/partners?${params}`);
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
  const params = new URLSearchParams({
    bloc: State.bloc,
    year: State.year,
    ...(State.country ? { country: State.country } : {}),
  });
  const data = await fetchJSON(`/api/concentration?${params}`);
  if (!isFresh(version)) return;
  document.getElementById("hhi-title").textContent = State.country ? `${scopeName()} · HHI vs peers` : "Partner concentration (HHI)";
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
    ? "Selected country - base = 100 - nominal USD"
    : `${State.bloc} members - base = 100 - nominal USD`;
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
  document.getElementById("conflict-title").textContent = `${scopeName()} · Conflict hotspots`;
  renderConflict(data.conflict || []);
  renderFragility(data.fragility || []);
}

async function loadHealth(version) {
  const data = await fetchJSON("/api/health");
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
