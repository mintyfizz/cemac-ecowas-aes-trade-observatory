/**
 * CEMAC-ECOWAS-AES Trade Observatory: static dashboard controller.
 *
 * Reads pre-computed JSON from data/ (built by scripts/offline_rebuild.py and
 * checked by scripts/check_static_contract.py). This file selects and labels
 * values; it does not aggregate, rescale or fill gaps. Missing values stay
 * missing and are shown as "--" with a reason where one is known.
 */

"use strict";

const BLOCS = ["CEMAC", "ECOWAS", "AES"];
const BLOC_LABEL = {
  CEMAC: "CEMAC",
  ECOWAS: "ECOWAS",
  AES: "AES (analytical cohort)",
};
const AES_MEMBERS = ["BFA", "MLI", "NER"];
const CURRENT_BLOC = {
  CMR: "CEMAC", CAF: "CEMAC", TCD: "CEMAC", COG: "CEMAC", GNQ: "CEMAC", GAB: "CEMAC",
  BEN: "ECOWAS", CPV: "ECOWAS", CIV: "ECOWAS", GMB: "ECOWAS", GHA: "ECOWAS", GIN: "ECOWAS",
  GNB: "ECOWAS", LBR: "ECOWAS", NGA: "ECOWAS", SEN: "ECOWAS", SLE: "ECOWAS", TGO: "ECOWAS",
  BFA: "AES", MLI: "AES", NER: "AES",
};

const MAP_METRICS = {
  openness: { label: "Trade openness (% of GDP)", col: "trade_openness_pct_gdp", format: v => fmtPct(v, 0) },
  trade: { label: "Goods trade (USD B, IMF World)", col: "total_trade_billions_usd", format: v => shortMoneyB(v) },
  top_partner: { label: "Top partner share of trade", col: "top_partner_share_of_world_pct", format: v => fmtPct(v, 1) },
  hhi: { label: "Partner concentration (HHI)", col: "total_trade_partner_hhi", format: v => fmtPlain(v, 3) },
  gdp: { label: "GDP (USD B)", col: "gdp_current_usd_billions", format: v => shortMoneyB(v) },
  fatalities_pm: { label: "Conflict fatalities per million", col: "fatalities_per_million", format: v => fmtPlain(v, 1) },
  fsi: { label: "FSI total (this edition year only)", col: "fsi_total_score", format: v => fmtPlain(v, 1) },
};

const DB = {};
const IDX = { ct: {}, bloc: {}, partners: {}, blocPartners: {}, hot: {}, frag: {} };
const State = { bloc: "CEMAC", year: 2024, country: null, mapMetric: "openness", loadVersion: 0 };
let YEARS = [];

// ---------------------------------------------------------------------------
// Data loading and indexing
// ---------------------------------------------------------------------------
async function fetchJSON(name) {
  const res = await fetch(`data/${name}`);
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  return res.json();
}

async function loadData() {
  const names = {
    ct: "country_timeseries.json",
    bloc: "bloc_comparison.json",
    partners: "top_trade_partners.json",
    blocPartners: "bloc_trade_partners.json",
    hot: "conflict_hotspots.json",
    frag: "fragility_components.json",
    products: "product_trade_hs2.json",
    prov: "provenance.json",
  };
  const entries = await Promise.all(Object.entries(names).map(async ([k, n]) => [k, await fetchJSON(n)]));
  Object.assign(DB, Object.fromEntries(entries));

  for (const r of DB.ct) (IDX.ct[r.country_iso3] ||= {})[r.year] = r;
  for (const r of DB.bloc) (IDX.bloc[r.analytical_bloc_code] ||= {})[r.year] = r;
  for (const r of DB.partners) (IDX.partners[`${r.country_iso3}|${r.year}`] ||= []).push(r);
  for (const r of DB.blocPartners) (IDX.blocPartners[`${r.analytical_bloc_code}|${r.year}`] ||= []).push(r);
  for (const list of [...Object.values(IDX.partners), ...Object.values(IDX.blocPartners)]) {
    list.sort((a, z) => a.partner_rank - z.partner_rank);
  }
  for (const r of DB.hot) (IDX.hot[r.country_iso3] ||= []).push(r);
  for (const list of Object.values(IDX.hot)) list.sort((a, z) => a.hotspot_rank - z.hotspot_rank);
  for (const r of DB.frag) IDX.frag[r.country_iso3] = r;
  YEARS = [...new Set(DB.ct.map(r => r.year))].sort((a, z) => a - z);
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function countryName(iso) {
  return IDX.ct[iso]?.[YEARS[YEARS.length - 1]]?.country_name || ISO3_NAMES[iso] || iso;
}

function blocOf(iso, year) {
  return IDX.ct[iso]?.[year]?.analytical_bloc_code || null;
}

function membersOf(bloc, year) {
  return IDX.bloc[bloc]?.[year]?.members || [];
}

function scopeName() {
  return State.country ? countryName(State.country) : BLOC_LABEL[State.bloc];
}

function fmtUsdPc(v) {
  return v == null ? "--" : `$${fmtNumber(v, 0)}`;
}

function reportingChip(n, m) {
  if (m == null || n == null) return "";
  if (n === m) return `<span class="chip ok">${n}/${m} countries</span>`;
  return `<span class="chip warn" title="Not all members report this value; the figure covers reporting members only">${n}/${m} countries</span>`;
}

function delta(current, previous, { digits = 1, kind = "pct", suffix = "" } = {}) {
  if (current == null || previous == null) return "";
  let d;
  if (kind === "pct") {
    if (previous === 0) return "";
    d = (current - previous) / Math.abs(previous) * 100;
    suffix = "%";
  } else {
    d = current - previous;
  }
  const cls = Math.abs(d) < 1e-9 ? "flat" : d > 0 ? "up" : "down";
  const arrow = cls === "up" ? "▲" : cls === "down" ? "▼" : "•";
  return `<span class="delta-badge ${cls}">${arrow} ${Math.abs(d).toFixed(digits)}${suffix}</span>`;
}

function kpi(id, label, valueHtml, noteHtml) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove("skeleton");
  el.innerHTML = `<div class="lbl">${escapeHTML(label)}</div><div class="val">${valueHtml}</div><div class="delta">${noteHtml || ""}</div>`;
}

function toast(message, duration = 6000) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("visible");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("visible"), duration);
}

// ---------------------------------------------------------------------------
// Scope view model: one place that maps country and bloc rows to the same fields
// ---------------------------------------------------------------------------
function scopeRow(year = State.year) {
  if (State.country) {
    const r = IDX.ct[State.country]?.[year];
    if (!r) return null;
    return {
      kind: "country",
      year,
      members: [State.country],
      memberCount: 1,
      tradeReporting: r.total_trade_billions_usd == null ? 0 : 1,
      gdpReporting: r.gdp_current_usd_billions == null ? 0 : 1,
      trade: r.total_trade_billions_usd,
      exports: r.exports_billions_usd,
      imports: r.imports_billions_usd,
      balance: r.trade_balance_billions_usd,
      openness: r.trade_openness_pct_gdp,
      expPct: r.exports_pct_gdp,
      impPct: r.imports_pct_gdp,
      balPct: r.trade_balance_pct_gdp,
      historicalOverlap: r.historical_successor_overlap,
      topPartnerCode: r.top_partner_iso3,
      topPartnerName: r.top_partner_name,
      topShare: r.top_partner_share_of_world_pct,
      top3Share: r.top3_partner_share_of_world_pct,
      hhi: r.total_trade_partner_hhi,
      namedCoverage: r.named_partner_coverage_pct,
      gdp: r.gdp_current_usd_billions,
      pop: r.population_millions,
      gdppc: r.gdp_per_capita_current_usd,
      growth: r.real_gdp_growth_pct_imf,
      inflation: r.inflation_cpi_pct,
      debt: r.gross_debt_pct_gdp_imf,
      fiscal: r.net_lending_borrowing_pct_gdp_imf,
      ca: r.current_account_balance_pct_gdp_imf,
      fatalitiesPm: r.fatalities_per_million,
      fatalities: r.fatalities,
      conflictNote: r.acled_covered ? null : "not in ACLED coverage for this year",
      fsi: r.fsi_total_score,
      fsiReporting: r.fsi_total_score == null ? 0 : 1,
      // A country contributes to a metric iff the metric is present.
      contrib: Object.fromEntries(Object.entries({
        trade: r.total_trade_billions_usd, gdp: r.gdp_current_usd_billions,
        openness: r.trade_openness_pct_gdp, conflict: r.fatalities_per_million,
      }).map(([k, v]) => [k, v == null ? [] : [State.country]])),
    };
  }
  const b = IDX.bloc[State.bloc]?.[year];
  if (!b) return null;
  return {
    kind: "bloc",
    year,
    members: b.members,
    memberCount: b.member_count,
    tradeReporting: b.trade_reporting,
    gdpReporting: b.gdp_reporting,
    trade: b.total_trade_billions_usd,
    exports: b.exports_billions_usd,
    imports: b.imports_billions_usd,
    balance: b.trade_balance_billions_usd,
    openness: b.trade_openness_pct_gdp,
    opennessCountries: b.openness_countries,
    expPct: b.exports_pct_gdp,
    impPct: b.imports_pct_gdp,
    balPct: b.trade_balance_pct_gdp,
    historicalOverlap: b.members.some(c => IDX.ct[c]?.[year]?.historical_successor_overlap),
    topPartnerCode: b.top_partner_code,
    topPartnerName: b.top_partner_name,
    topShare: b.top_partner_share_of_world_pct,
    top3Share: b.top3_partner_share_of_world_pct,
    hhi: b.bloc_partner_hhi,
    namedCoverage: b.named_partner_coverage_pct,
    gdp: b.gdp_current_usd_billions,
    pop: b.population_millions,
    gdppc: b.gdp_per_capita_current_usd,
    growth: b.real_gdp_growth_pct_weighted,
    inflation: b.inflation_pct_weighted,
    debt: b.gross_debt_pct_gdp_weighted,
    fiscal: b.net_lending_borrowing_pct_gdp_weighted,
    ca: b.current_account_pct_gdp_weighted,
    macroMembers: {
      growth: b.growth_members, inflation: b.inflation_members, debt: b.gross_debt_members,
      fiscal: b.fiscal_members, ca: b.current_account_members, pop: b.population_members,
    },
    fatalitiesPm: b.fatalities_per_million,
    fatalities: b.fatalities,
    conflictReporting: b.conflict_reporting,
    conflictNote: b.conflict_reporting === 0 ? "no member in ACLED coverage for this year" : null,
    fsi: b.fsi_total_score_mean,
    fsiReporting: b.fsi_reporting,
    contrib: { trade: b.trade_members, gdp: b.gdp_members, openness: b.openness_members, conflict: b.conflict_members },
  };
}

function comparablePrevious(cur) {
  if (!cur) return null;
  const prev = scopeRow(State.year - 1);
  if (!prev) return null;
  if (cur.kind === "bloc" && prev.members.join("|") !== cur.members.join("|")) return null;
  return prev;
}

// Previous-year value only when the same countries contribute in both years.
function matchedPrev(cur, prev, metric, field) {
  if (!cur || !prev) return null;
  const a = (cur.contrib?.[metric] || []).join("|");
  const b = (prev.contrib?.[metric] || []).join("|");
  return a && a === b ? prev[field] : null;
}

// ---------------------------------------------------------------------------
// URL state (shareable, back/forward)
// ---------------------------------------------------------------------------
function readUrl() {
  const p = new URLSearchParams(location.search);
  const year = Number(p.get("year"));
  if (YEARS.includes(year)) State.year = year;
  const bloc = p.get("bloc");
  if (BLOCS.includes(bloc)) State.bloc = bloc;
  const country = p.get("country");
  State.country = country && IDX.ct[country] ? country : null;
  const metric = p.get("metric");
  if (MAP_METRICS[metric]) State.mapMetric = metric;
  if (State.country) State.bloc = blocOf(State.country, State.year) || State.bloc;
}

function writeUrl(push = true) {
  const p = new URLSearchParams();
  p.set("bloc", State.bloc);
  p.set("year", String(State.year));
  if (State.country) p.set("country", State.country);
  if (State.mapMetric !== "openness") p.set("metric", State.mapMetric);
  const url = `${location.pathname}?${p.toString()}${location.hash}`;
  if (url === `${location.pathname}${location.search}${location.hash}`) return;
  if (push) history.pushState(null, "", url);
  else history.replaceState(null, "", url);
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
function populateControls() {
  const yearSel = document.getElementById("year-select");
  yearSel.innerHTML = [...YEARS].reverse().map(y => `<option value="${y}">${y}</option>`).join("");
  const metricSel = document.getElementById("metric-select");
  metricSel.innerHTML = Object.entries(MAP_METRICS).map(([k, m]) => `<option value="${k}">${escapeHTML(m.label)}</option>`).join("");
  const countrySel = document.getElementById("country-select");
  const groups = BLOCS.map(b => {
    const isos = Object.keys(CURRENT_BLOC).filter(c => CURRENT_BLOC[c] === b).sort((a, z) => countryName(a).localeCompare(countryName(z)));
    return `<optgroup label="${b} (current)">${isos.map(c => `<option value="${c}">${escapeHTML(countryName(c))}</option>`).join("")}</optgroup>`;
  }).join("");
  countrySel.innerHTML = `<option value="">All countries in bloc</option>${groups}`;
}

function syncControls() {
  document.getElementById("year-select").value = String(State.year);
  document.getElementById("metric-select").value = State.mapMetric;
  document.getElementById("country-select").value = State.country || "";
  document.querySelectorAll(".bloc-btn").forEach(btn => {
    const on = btn.dataset.bloc === State.bloc;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function attachListeners() {
  document.getElementById("bloc-tabs").addEventListener("click", e => {
    const btn = e.target.closest(".bloc-btn");
    if (!btn) return;
    State.bloc = btn.dataset.bloc;
    State.country = null;
    if (!membersOf(State.bloc, State.year).length) {
      toast(`${BLOC_LABEL[State.bloc]} exists in the data only for 2024; showing 2024.`);
      State.year = 2024;
    }
    update();
  });
  document.getElementById("year-select").addEventListener("change", e => {
    State.year = Number(e.target.value);
    if (State.country) {
      State.bloc = blocOf(State.country, State.year) || State.bloc;
    } else if (!membersOf(State.bloc, State.year).length) {
      toast(`${BLOC_LABEL[State.bloc]} has no members in ${State.year} under the analytical cohort rule; showing ECOWAS.`);
      State.bloc = "ECOWAS";
    }
    update();
  });
  document.getElementById("metric-select").addEventListener("change", e => {
    State.mapMetric = e.target.value;
    update();
  });
  document.getElementById("country-select").addEventListener("change", e => {
    selectCountry(e.target.value || null);
  });
  window.addEventListener("popstate", () => {
    readUrl();
    render();
  });
}

function selectCountry(iso) {
  if (!iso || iso === State.country) {
    State.country = null;
  } else {
    State.country = iso;
    State.bloc = blocOf(iso, State.year) || State.bloc;
  }
  update();
}
window.dashboardSelectCountry = selectCountry;

function update() {
  writeUrl(true);
  render();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function renderCrumb() {
  const el = document.getElementById("crumb");
  const yr = State.year;
  if (State.country) {
    const b = blocOf(State.country, yr);
    el.innerHTML = `<button class="back-btn" type="button" id="back-btn">← ${escapeHTML(BLOC_LABEL[b] || b)}</button>
      <span class="crumb-sep">/</span><b>${escapeHTML(countryName(State.country))}</b>
      <span class="crumb-sep">·</span>${yr}<span class="crumb-sep">·</span>analytical bloc in ${yr}: ${escapeHTML(BLOC_LABEL[b] || b)}`;
    document.getElementById("back-btn").addEventListener("click", () => selectCountry(null));
  } else {
    const m = membersOf(State.bloc, yr);
    el.innerHTML = `<b>${escapeHTML(BLOC_LABEL[State.bloc])}</b><span class="crumb-sep">·</span>${yr}<span class="crumb-sep">·</span>${m.length} member${m.length === 1 ? "" : "s"}: ${m.map(c => countryName(c)).sort((a, z) => a.localeCompare(z)).map(escapeHTML).join(", ")}`;
  }
  const notice = document.getElementById("cohort-notice");
  const showCohort = State.year >= 2024 && (State.bloc === "AES" || State.bloc === "ECOWAS" || AES_MEMBERS.includes(State.country));
  notice.hidden = !showCohort;
  if (showCohort) {
    notice.innerHTML = `<b>Analytical cohort.</b> Burkina Faso, Mali and Niger are grouped as AES from the AES confederation treaty (6 July 2024).
      Their legal withdrawal from ECOWAS took effect on 29 January 2025, so in 2024 they were still legally ECOWAS members.
      ECOWAS in 2024 here means the 12 other members. Earlier years group all 15 as ECOWAS.`;
  }
}

function renderOverview() {
  const cur = scopeRow();
  const prev = comparablePrevious(cur);
  document.getElementById("overview-period").textContent = `${scopeName()} · ${State.year}`;
  if (!cur) {
    ["kpi-trade", "kpi-open", "kpi-partner", "kpi-hhi", "kpi-gdp", "kpi-conflict"].forEach(id => kpi(id, "", "--", "no data"));
    return;
  }
  const n = cur.memberCount;
  kpi("kpi-trade", "Goods trade", shortMoneyB(cur.trade),
    `${delta(cur.trade, matchedPrev(cur, prev, "trade", "trade"))} exports + imports, IMF World ${cur.kind === "bloc" ? reportingChip(cur.tradeReporting, n) : ""}`);
  kpi("kpi-open", "Trade openness", fmtPct(cur.openness, 1),
    `${delta(cur.openness, matchedPrev(cur, prev, "openness", "openness"), { kind: "abs", suffix: " pp" })} % of GDP ${cur.kind === "bloc" ? reportingChip(cur.opennessCountries, n) : ""}`);
  const tp = cur.topPartnerCode ? partnerLabel(cur.topPartnerCode, cur.topPartnerName) : "--";
  kpi("kpi-partner", "Top partner", escapeHTML(tp),
    cur.topShare == null ? "share unavailable (incomplete reporting)" : `${fmtPct(cur.topShare)} of trade · top 3: ${fmtPct(cur.top3Share)}`);
  kpi("kpi-hhi", "Partner concentration", fmtPlain(cur.hhi, 3),
    `HHI over named partners · ${cur.namedCoverage == null ? "coverage n/a" : `named partners = ${fmtPct(cur.namedCoverage, 0)} of World`}`);
  kpi("kpi-gdp", "GDP", shortMoneyB(cur.gdp),
    `${delta(cur.gdp, matchedPrev(cur, prev, "gdp", "gdp"))} current USD ${cur.kind === "bloc" ? reportingChip(cur.gdpReporting, n) : ""}`);
  kpi("kpi-conflict", "Conflict fatalities", cur.fatalitiesPm == null ? "--" : `${fmtPlain(cur.fatalitiesPm, 1)}<small>/m</small>`,
    cur.conflictNote ? escapeHTML(cur.conflictNote)
      : `${fmtNumber(cur.fatalities)} fatalities in ${State.year} (ACLED) ${cur.kind === "bloc" ? reportingChip(cur.conflictReporting, n) : ""}`);

  const mm = cur.macroMembers || {};
  const chip = key => (cur.kind === "bloc" && mm[key] ? reportingChip(mm[key].length, n) : "");
  const econ = [
    ["Population", cur.pop == null ? "--" : `${fmtPlain(cur.pop, 1)}M`, "millions", chip("pop")],
    ["GDP per capita", fmtUsdPc(cur.gdppc), cur.kind === "bloc" && cur.gdppc == null && cur.gdp != null ? "not shown: GDP and population cover different members" : "current USD", ""],
    ["Real GDP growth", fmtPct(cur.growth), cur.kind === "bloc" ? "GDP-weighted" : "annual %", chip("growth")],
    ["Inflation", fmtPct(cur.inflation), cur.kind === "bloc" ? "GDP-weighted, avg CPI" : "avg consumer prices", chip("inflation")],
    ["Govt gross debt", fmtPct(cur.debt), cur.kind === "bloc" ? "% of GDP, GDP-weighted" : "% of GDP", chip("debt")],
    ["Fiscal balance", fmtPct(cur.fiscal), cur.kind === "bloc" ? "net lending/borrowing, % of GDP, GDP-weighted" : "net lending/borrowing, % of GDP", chip("fiscal")],
    ["Current account", fmtPct(cur.ca), cur.kind === "bloc" ? "% of GDP, GDP-weighted" : "% of GDP", chip("ca")],
    ["Exports / GDP", fmtPct(cur.expPct), "goods, IMF World", cur.kind === "bloc" ? reportingChip(cur.opennessCountries, n) : ""],
    ["Imports / GDP", fmtPct(cur.impPct), "goods, IMF World", cur.kind === "bloc" ? reportingChip(cur.opennessCountries, n) : ""],
    ["FSI total", cur.fsi == null ? "--" : fmtPlain(cur.fsi, 1),
      cur.fsi == null ? `no FSI edition for ${State.year} in the data` : (cur.kind === "bloc" ? `mean, ${State.year} edition` : `${State.year} edition`),
      cur.kind === "bloc" && cur.fsi != null ? reportingChip(cur.fsiReporting, n) : ""],
  ];
  document.getElementById("econ-scope").textContent = `${scopeName()}, ${State.year}`;
  document.getElementById("econ-grid").innerHTML = econ.map(([l, v, d, c]) =>
    `<div class="econ-card"><div class="lbl">${escapeHTML(l)}</div><div class="val">${v}</div><div class="desc">${escapeHTML(d)} ${c || ""}</div></div>`).join("");
}

function renderMapPanel() {
  const meta = MAP_METRICS[State.mapMetric];
  document.getElementById("map-title").textContent = `${meta.label} · ${State.year}`;
  const rows = DB.ct.filter(r => r.year === State.year).map(r => ({
    country_iso3: r.country_iso3,
    country_name: r.country_name,
    analytical_bloc_code: r.analytical_bloc_code,
    value: r[meta.col] ?? null,
  }));
  const withData = rows.filter(r => r.value != null).length;
  document.getElementById("map-sub").textContent = withData
    ? `${withData}/21 countries with data · select a country on the map or in the Country menu`
    : `No ${meta.label.toLowerCase()} values for ${State.year} · select another year or metric`;
  State.loadVersion += 1;
  renderMap(rows, State, meta, State.loadVersion);
}

function renderPartners() {
  const key = State.country ? `${State.country}|${State.year}` : `${State.bloc}|${State.year}`;
  const rows = (State.country ? IDX.partners[key] : IDX.blocPartners[key]) || [];
  const cur = scopeRow();
  document.getElementById("partners-title").textContent = `${scopeName()} · top 10 named partners · ${State.year}`;
  renderPartnerBars(rows);
  const note = document.getElementById("partners-note");
  if (!State.country && cur && cur.topShare == null) {
    note.textContent = "Shares of World trade are not shown because not every member reports trade this year.";
  } else {
    note.textContent = State.country
      ? "Partners are named economies; IMF regional aggregates are excluded."
      : "Bloc partners aggregate all members' named partners. Members' combined trade includes trade between members, marked 'member'.";
  }
  if (cur?.historicalOverlap) {
    note.textContent += " In this year the source reports trade with both a former economy (e.g. USSR, Yugoslavia, Czechoslovakia) and one of its successors, so named partners may overlap; values are shown as published.";
  }

  // Dependence trend
  const series = YEARS.map(y => scopeRowAt(y));
  document.getElementById("dependence-title").textContent = `${scopeName()} · partner dependence over time`;
  document.getElementById("dependence-summary").innerHTML = cur ? `
    <div class="diag-chip"><span class="lbl">Top partner ${State.year}</span><span class="val">${escapeHTML(cur.topPartnerCode ? partnerLabel(cur.topPartnerCode, cur.topPartnerName) : "--")}</span><span class="desc">${fmtPct(cur.topShare)} of World trade</span></div>
    <div class="diag-chip"><span class="lbl">Top 3 partners</span><span class="val">${fmtPct(cur.top3Share)}</span><span class="desc">of World trade</span></div>
    <div class="diag-chip"><span class="lbl">Named coverage</span><span class="val">${fmtPct(cur.namedCoverage, 0)}</span><span class="desc">named partners vs World</span></div>` : "";
  document.getElementById("dependence-break").textContent = State.country
    ? ""
    : "Bloc series use each year's membership; 2024 is a composition break (ECOWAS 15 to 12 members, AES cohort starts).";
  renderLines("dependence-chart", YEARS, [
    { label: "Top partner share", color: COLORS.warning, values: series.map(s => s?.topShare ?? null) },
    { label: "Top 3 share", color: COLORS.imports, values: series.map(s => s?.top3Share ?? null) },
  ], { yTitle: "% of World trade", format: v => fmtPct(v), selectedYear: State.year, yMin: 0, breakYear: State.country ? null : 2024 });

  // HHI: bloc-grain lines for all blocs; selected country overlaid
  const hhiSeries = BLOCS.map(b => ({
    label: `${b} (bloc)`,
    color: blocColor(b),
    width: !State.country && b === State.bloc ? 2.6 : 1.2,
    values: YEARS.map(y => IDX.bloc[b]?.[y]?.bloc_partner_hhi ?? null),
  }));
  if (State.country) {
    hhiSeries.push({ label: countryName(State.country), color: COLORS.text, width: 2.6,
      values: YEARS.map(y => IDX.ct[State.country]?.[y]?.total_trade_partner_hhi ?? null) });
  }
  renderLines("hhi-chart", YEARS, hhiSeries, { yTitle: "HHI (0–1)", format: v => fmtPlain(v, 3), selectedYear: State.year, yMin: 0, breakYear: 2024 });
  document.getElementById("hhi-sub").textContent = State.country
    ? `${countryName(State.country)}: HHI over its named partners. Bloc lines: HHI over members' combined named partners.`
    : "Bloc lines: HHI over members' combined named partners (includes trade between members). Not a risk rating.";

  // Coverage
  const covSeries = State.country
    ? [{ label: countryName(State.country), color: COLORS.text, values: YEARS.map(y => IDX.ct[State.country]?.[y]?.named_partner_coverage_pct ?? null) }]
    : membersOf(State.bloc, State.year).map(c => ({ label: c, color: seriesColor(c, State.bloc), width: 1.4,
      values: YEARS.map(y => IDX.ct[c]?.[y]?.named_partner_coverage_pct ?? null) }));
  renderLines("coverage-chart", YEARS, covSeries, { yTitle: "% of World total", format: v => fmtPct(v, 1), selectedYear: State.year });
}

function scopeRowAt(year) {
  const saved = State.year;
  const row = scopeRow(year);
  State.year = saved;
  return row;
}

function renderExposure() {
  // Openness: bloc lines (bloc rows; membership changes in 2024 are marked by the cohort note)
  const openSeries = BLOCS.map(b => ({
    label: b, color: blocColor(b), width: !State.country && b === State.bloc ? 2.6 : 1.2,
    values: YEARS.map(y => IDX.bloc[b]?.[y]?.trade_openness_pct_gdp ?? null),
  }));
  if (State.country) {
    openSeries.push({ label: countryName(State.country), color: COLORS.text, width: 2.6,
      values: YEARS.map(y => IDX.ct[State.country]?.[y]?.trade_openness_pct_gdp ?? null) });
  }
  document.getElementById("openness-title").textContent = `Trade openness · ${State.country ? countryName(State.country) + " vs blocs" : "blocs"}`;
  renderLines("openness-chart", YEARS, openSeries, { yTitle: "% of GDP", format: v => fmtPct(v, 1), selectedYear: State.year, yMin: 0, breakYear: 2024 });

  // Growth index: fixed cohort = selected scope's members in the selected year
  const cohort = State.country ? [State.country] : membersOf(State.bloc, State.year);
  const totals = YEARS.map(y => {
    const vals = cohort.map(c => IDX.ct[c]?.[y]?.total_trade_billions_usd);
    return vals.some(v => v == null) ? null : vals.reduce((s, v) => s + v, 0);
  });
  const base = totals[0];
  const idx = totals.map(v => (v == null || !base) ? null : v / base * 100);
  const finite = idx.filter(v => v != null && v > 0);
  const log = finite.length && Math.max(...finite) / Math.min(...finite) > 15;
  document.getElementById("growth-title").textContent = `${scopeName()} · goods trade indexed to 1990`;
  document.getElementById("growth-sub").textContent = `1990 = 100 · nominal USD${log ? " · log scale" : ""}`;
  document.getElementById("growth-note").textContent = State.country
    ? "IMF World total for this country. Nominal USD: includes price and exchange-rate effects."
    : `Fixed cohort: the ${cohort.length} members in ${State.year}, summed across all years. Years where any member lacks data are gaps.`;
  renderLines("growth-chart", YEARS, [{ label: scopeName(), color: State.country ? COLORS.text : blocColor(State.bloc), values: idx }],
    { yTitle: "Index", format: v => fmtPlain(v, 0), selectedYear: State.year, log });

  const cur = scopeRow();
  document.getElementById("exposure-title").textContent = `${scopeName()} · exposure profile · ${State.year}`;
  // Balance % of GDP comes pre-computed over the same contributors as exports/imports % of GDP.
  const balPct = cur?.balPct ?? null;
  renderBars("exposure-chart", ["Exports", "Imports", "Trade balance"], [{
    label: "% of GDP",
    color: [COLORS.exports, COLORS.imports, balPct != null && balPct < 0 ? COLORS.danger : COLORS.success],
    values: [cur?.expPct ?? null, cur?.impPct ?? null, balPct],
  }], { xTitle: "% of GDP", format: v => fmtPct(v, 1) });
  const sub = document.querySelector("#exposure-title + .sub");
  if (sub) {
    sub.textContent = cur?.kind === "bloc"
      ? `Exports, imports and trade balance as % of GDP, ${State.year} · ${cur.opennessCountries}/${cur.memberCount} members with both trade and GDP`
      : `Exports, imports and trade balance as % of GDP, ${State.year}`;
  }
}

function renderProductsPanel() {
  const p = DB.products || {};
  document.getElementById("products-reason").textContent = p.reason || "Product data unavailable.";

}

function renderContext() {
  const win = DB.prov?.acled?.hotspot_window || [2022, 2024];
  const members = State.country ? [State.country] : Object.keys(CURRENT_BLOC).filter(c => CURRENT_BLOC[c] === State.bloc);
  const scope = State.country ? countryName(State.country) : `${State.bloc} (current members)`;
  if (State.country) {
    const rows = (IDX.hot[State.country] || []).slice(0, 10);
    document.getElementById("conflict-title").textContent = `${scope} · conflict hotspots`;
    document.getElementById("conflict-sub").textContent = `ACLED · first-level admin areas · ${win[0]}–${win[1]} combined`;
    renderBars("conflict-chart", rows.map(r => r.admin1), [
      { label: "Violent events", color: COLORS.warning, values: rows.map(r => r.violent_events) },
      { label: "Fatalities", color: COLORS.danger, values: rows.map(r => r.fatalities) },
    ], { xTitle: "count", format: v => fmtNumber(v) });
    const all = IDX.hot[State.country] || [];
    document.getElementById("conflict-note").textContent =
      `${all.length} admin areas with events; top ${rows.length} shown, ranked by violent events then fatalities. Violent events = battles, explosions/remote violence, violence against civilians, riots.`;
  } else {
    const rows = members.map(c => {
      const list = IDX.hot[c] || [];
      return {
        c,
        ve: list.reduce((s, r) => s + r.violent_events, 0),
        fat: list.reduce((s, r) => s + r.fatalities, 0),
      };
    }).sort((a, z) => z.ve - a.ve || z.fat - a.fat);
    document.getElementById("conflict-title").textContent = `${scope} · conflict by country`;
    document.getElementById("conflict-sub").textContent = `ACLED · ${win[0]}–${win[1]} combined · counts`;
    renderBars("conflict-chart", rows.map(r => countryName(r.c)), [
      { label: "Violent events", color: COLORS.warning, values: rows.map(r => r.ve) },
      { label: "Fatalities", color: COLORS.danger, values: rows.map(r => r.fat) },
    ], { xTitle: "count", format: v => fmtNumber(v) });
    document.getElementById("conflict-note").textContent =
      "Counts, not rates. Per-million rates for the selected year are in the Overview. Violent events = battles, explosions/remote violence, violence against civilians, riots.";
  }

  const frag = members.map(c => IDX.frag[c]).filter(Boolean);
  const editions = [...new Set(frag.map(f => f.fsi_year))].sort();
  document.getElementById("fragility-title").textContent = `${scope} · fragility pillars`;
  document.getElementById("fragility-sub").textContent = editions.length
    ? `Fund for Peace FSI · latest edition loaded: ${editions.join(", ")} · independent of the selected year`
    : "No FSI edition loaded for this scope";
  const fr = [...frag].sort((a, z) => (z.fsi_total_score ?? 0) - (a.fsi_total_score ?? 0));
  renderBars("fragility-chart", fr.map(f => `${countryName(f.country_iso3)} (${f.fsi_year})`), [
    { label: "Cohesion", color: "#c084fc", values: fr.map(f => f.cohesion_score) },
    { label: "Economic", color: "#60a5fa", values: fr.map(f => f.economic_score) },
    { label: "Political", color: "#f59e0b", values: fr.map(f => f.political_score) },
    { label: "Social & cross-cutting", color: "#34d399", values: fr.map(f => f.social_cross_cutting_score) },
  ], { stacked: true, xTitle: "FSI points", format: v => fmtPlain(v, 1) });
}

function renderSources() {
  const p = DB.prov;
  if (!p) return;
  const sha = k => (p.raw_inputs?.[k]?.sha256 || "").slice(0, 12);
  const dates = arr => (arr || []).map(d => String(d).slice(0, 10)).filter((v, i, a) => a.indexOf(v) === i).join(", ");
  const outliers = (p.source_outliers || []).map(o => `${escapeHTML(countryName(o.country_iso3))} ${o.year} (${fmtPct(o.value, 0)})`).join("; ");
  const cud = Object.values(p.weo?.country_update_date_by_country || {}).flat();
  const cudRange = cud.length ? `${cud.sort((a, z) => new Date(a) - new Date(z))[0]} to ${cud[cud.length - 1]}` : "n/a";
  document.getElementById("sources").innerHTML = `
    <table class="src-table">
      <thead><tr><th>Source</th><th>Used for</th><th>Period</th><th>Snapshot</th></tr></thead>
      <tbody>
        <tr><td>IMF International Merchandise Trade Statistics (IMTS)</td><td>Goods exports (FOB), imports (CIF), named partners</td><td>${p.years[0]}–${p.years[1]}, annual</td><td>extracted ${dates(p.imts?.extracted_at)} · sha256 ${sha("imts")}</td></tr>
        <tr><td>IMF World Economic Outlook (WEO)</td><td>GDP, population, growth, inflation, debt, fiscal and current-account balances</td><td>${p.years[0]}–${p.years[1]}, annual</td><td>extracted ${dates(p.weo?.extracted_at)} · country update dates ${escapeHTML(cudRange)} · release vintage ${escapeHTML(p.weo?.release_vintage || "not recorded")} · sha256 ${sha("weo")}</td></tr>
        <tr><td>ACLED</td><td>Conflict events and fatalities</td><td>from the first year with an observed event per country (1997 for most; Cabo Verde 2020) to ${p.years[1]}. This is a coverage heuristic, not ACLED's confirmed coverage start.</td><td>extracted ${dates(p.acled?.extracted_at_range)} · ${fmtNumber(p.acled?.events)} events · sha256 ${sha("acled")}</td></tr>
        <tr><td>Fund for Peace, Fragile States Index</td><td>Fragility total and pillars</td><td>editions ${p.fsi?.years?.[0]}–${p.fsi?.years?.[1]}</td><td>extracted ${dates(p.fsi?.extracted_at)} · sha256 ${sha("fsi")}</td></tr>
        <tr><td>UN Comtrade</td><td>Product (HS2) structure</td><td colspan="2"><b>Quarantined.</b> ${escapeHTML(p.products?.reason || "")}</td></tr>
      </tbody>
    </table>
    <div class="method-grid">
      <div><h4>Bloc membership</h4><p>${escapeHTML(p.membership_rule)}</p></div>
      <div><h4>Trade totals and partners</h4><p>${escapeHTML(p.imts?.headline_rule || "")} ${escapeHTML(p.imts?.share_rule || "")} ${escapeHTML(p.imts?.world_minus_named_note || "")}
        Counterpart codes are classified with the IMF codelist (${escapeHTML(p.imts?.codelist || "")}); former or combined economies seen: ${escapeHTML((p.imts?.historical_or_combined_named_codes_seen || []).join(", ") || "none")}.</p></div>
      <div><h4>Bloc figures</h4><p>Bloc totals are sums of members' IMF World totals and include trade between members. Openness divides trade by GDP over the same reporting members. Ratios such as debt and growth are GDP-weighted. Each bloc figure states how many members report it, and year-on-year changes are only shown when membership is unchanged.</p></div>
      <div><h4>Conflict</h4><p>${escapeHTML(p.acled?.coverage_rule || "")} Rates are fatalities (or events) divided by population in millions for the same year. ${escapeHTML(p.acled?.hotspot_rule || "")}</p></div>
      <div><h4>Fragility</h4><p>FSI values appear only for the edition year they belong to; earlier years are never filled with later editions. The context panel shows each country's latest loaded edition with its year. ${escapeHTML(p.fsi?.note || "")}${(p.fsi_source_inconsistencies || []).length ? ` Source note: ${p.fsi_source_inconsistencies.map(f => `${escapeHTML(f.country_iso3)} ${f.year} indicators sum to ${f.indicator_sum} vs published total ${f.published_total}`).join("; ")}.` : ""}</p></div>
      <div><h4>Former and successor economies</h4><p>Partner rows keep former or combined economies (such as the USSR, Yugoslavia, Czechoslovakia, Belgium-Luxembourg) as published. In ${fmtNumber((p.imts?.historical_successor_overlaps || []).length)} reporter-year-flows the source also reports a successor in the same year (${fmtNumber((p.imts?.historical_successor_overlaps || []).filter(o => o.values_within_half_percent).length)} of them with nearly identical values). Named partners are therefore not guaranteed to be geographically disjoint in those years; affected views say so. Values are not removed or redistributed. World totals are unaffected.</p></div>
      <div><h4>Flagged source values</h4><p>Openness above 200% of GDP (kept as published, not corrected): ${outliers || "none"}. Named-partner coverage differs from the World total by more than 2% in ${fmtNumber(p.imts?.country_years_named_coverage_off_by_more_than_2pct)} country-years (see the coverage chart).</p></div>
    </div>
    <details class="tech-details">
      <summary>Technical details for maintainers</summary>
      <p>Product data revalidation:</p>
      <ol>${(DB.products?.revalidation || []).map(s => `<li>${escapeHTML(s)}</li>`).join("")}</ol>
      <p>Rebuild: <code>python scripts/offline_rebuild.py --raw-dir &lt;raw snapshots&gt;</code>, then <code>python scripts/check_static_contract.py --raw-dir &lt;raw snapshots&gt;</code>.</p>
    </details>
    <p class="note">Data files and derived datasets remain subject to their providers' terms.</p>`;
}

function render() {
  syncControls();
  renderCrumb();
  renderOverview();
  renderMapPanel();
  renderPartners();
  renderExposure();
  renderContext();
}

async function init() {
  try {
    await loadData();
  } catch (err) {
    toast(`Could not load dashboard data: ${err.message}`, 15000);
    return;
  }
  State.year = YEARS[YEARS.length - 1];
  populateControls();
  readUrl();
  if (!State.country && !membersOf(State.bloc, State.year).length) State.bloc = "ECOWAS";
  writeUrl(false);
  attachListeners();
  renderProductsPanel();
  renderSources();
  render();
}

document.addEventListener("DOMContentLoaded", init);
