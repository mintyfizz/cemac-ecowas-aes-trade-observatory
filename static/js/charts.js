/**
 * Chart and map renderers for the CEMAC-ECOWAS-AES dashboard.
 * D3 map + Chart.js. Rendering only: every number arrives pre-computed from
 * static/data (see scripts/offline_rebuild.py); no aggregation happens here.
 */

"use strict";

const COLORS = {
  CEMAC: "#0f6e56",
  ECOWAS: "#185fa5",
  AES: "#ba7517",
  exports: "#1d9e75",
  imports: "#7f77dd",
  text: "#f4f1e8",
  muted: "#aaa59a",
  grid: "#44453f",
  surface: "#2f302d",
  danger: "#ef7668",
  success: "#7ed66d",
  warning: "#f7d25d",
  purple: "#7f77dd",
  teal: ["#0b3327", "#0f4f40", "#116d57", "#16896f", "#1da986"],
};

const COUNTRY_NUMERIC_TO_ISO = {
  "120": "CMR", "140": "CAF", "148": "TCD", "178": "COG", "226": "GNQ", "266": "GAB",
  "204": "BEN", "854": "BFA", "132": "CPV", "384": "CIV", "270": "GMB", "288": "GHA",
  "324": "GIN", "624": "GNB", "430": "LBR", "466": "MLI", "562": "NER", "566": "NGA",
  "686": "SEN", "694": "SLE", "768": "TGO",
};

const COUNTRY_COLORS = {
  CMR: "#2dd4bf", CAF: "#fb7185", TCD: "#facc15", COG: "#60a5fa", GNQ: "#c084fc", GAB: "#34d399",
  BEN: "#38bdf8", BFA: "#f97316", CPV: "#a3e635", CIV: "#f59e0b", GMB: "#e879f9", GHA: "#22c55e",
  GIN: "#06b6d4", GNB: "#f43f5e", LBR: "#818cf8", MLI: "#fbbf24", NER: "#10b981", NGA: "#3b82f6",
  SEN: "#eab308", SLE: "#14b8a6", TGO: "#a78bfa",
};

const NEIGHBOR_NUMERIC = new Set(["478", "012", "12", "434", "729", "728", "180", "024", "24", "678", "504", "732"]);

// Full country names keyed by ISO 3166-1 alpha-3 code.
// Used wherever the API returns raw ISO3 codes as counterpart_name.
const ISO3_NAMES = {
  // Project countries
  BEN:"Benin", BFA:"Burkina Faso", CAF:"Central African Rep.", CMR:"Cameroon",
  COG:"Congo", CPV:"Cabo Verde", CIV:"Côte d'Ivoire", GAB:"Gabon",
  GHA:"Ghana", GIN:"Guinea", GMB:"Gambia", GNB:"Guinea-Bissau",
  GNQ:"Equatorial Guinea", LBR:"Liberia", MLI:"Mali", NER:"Niger",
  NGA:"Nigeria", SEN:"Senegal", SLE:"Sierra Leone", TCD:"Chad", TGO:"Togo",
  // Major global partners
  ARE:"UAE", ARG:"Argentina", AUS:"Australia", AUT:"Austria",
  BEL:"Belgium", BGD:"Bangladesh", BRA:"Brazil", CAN:"Canada",
  CHE:"Switzerland", CHL:"Chile", CHN:"China", COL:"Colombia",
  DEU:"Germany", DNK:"Denmark", DZA:"Algeria", EGY:"Egypt",
  ESP:"Spain", ETH:"Ethiopia", FIN:"Finland", FRA:"France",
  GBR:"United Kingdom", GRC:"Greece", HKG:"Hong Kong", IDN:"Indonesia",
  IND:"India", IRL:"Ireland", IRN:"Iran", IRQ:"Iraq",
  ISR:"Israel", ITA:"Italy", JPN:"Japan", KAZ:"Kazakhstan",
  KOR:"South Korea", KWT:"Kuwait", LBN:"Lebanon", LBY:"Libya",
  MAR:"Morocco", MEX:"Mexico", MYS:"Malaysia", NGA:"Nigeria",
  NLD:"Netherlands", NOR:"Norway", OMN:"Oman", PAK:"Pakistan",
  PHL:"Philippines", POL:"Poland", PRT:"Portugal", QAT:"Qatar",
  ROU:"Romania", RUS:"Russia", SAU:"Saudi Arabia", SDN:"Sudan",
  SGP:"Singapore", SWE:"Sweden", THA:"Thailand", TUN:"Tunisia",
  TUR:"Turkey", TWN:"Taiwan", UKR:"Ukraine", USA:"United States",
  VNM:"Vietnam", ZAF:"South Africa", ZMB:"Zambia", ZWE:"Zimbabwe",
  // Additional African countries
  AGO:"Angola", BDI:"Burundi", BWA:"Botswana", COM:"Comoros",
  CPV:"Cabo Verde", DJI:"Djibouti", ERI:"Eritrea", KEN:"Kenya",
  LSO:"Lesotho", MDG:"Madagascar", MOZ:"Mozambique", MRT:"Mauritania",
  MUS:"Mauritius", MWI:"Malawi", NAM:"Namibia", RWA:"Rwanda",
  SOM:"Somalia", SSD:"South Sudan", SWZ:"Eswatini", TZA:"Tanzania",
  UGA:"Uganda",
};

const chartStore = {};
let worldPromise = null;

if (window.Chart) {
  Chart.defaults.color = COLORS.text;
  Chart.defaults.font.family = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif';
  Chart.defaults.font.size = 11;
  Chart.defaults.borderColor = COLORS.grid;
}

function destroyChart(id) {
  if (chartStore[id]) {
    chartStore[id].destroy();
    delete chartStore[id];
  }
}

function canvas(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  destroyChart(id);
  el.parentElement?.querySelectorAll(".empty-state").forEach(node => node.remove());
  return el;
}

function lineOptions(title, yTitle, extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    transitions: {
      active: { animation: { duration: 0 } },
      resize: { animation: { duration: 0 } },
    },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 3, usePointStyle: true, pointStyle: "line" } },
      title: { display: !!title, text: title, color: COLORS.text, font: { size: 12, weight: "500" } },
      tooltip: { backgroundColor: "#11120f", borderColor: "#55564f", borderWidth: 1 },
    },
    scales: {
      x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, maxRotation: 0 } },
      y: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text }, title: { display: !!yTitle, text: yTitle, color: COLORS.text } },
    },
    ...extra,
  };
}

function barOptions(title, xTitle, extra = {}) {
  return lineOptions(title, xTitle, {
    indexAxis: "y",
    // For horizontal bars the index runs along y, so hover must use axis:"y"
    // otherwise Chart.js scans by x-position and the tooltip fires at wrong rows.
    interaction: { mode: "index", axis: "y", intersect: false },
    scales: {
      x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text }, title: { display: !!xTitle, text: xTitle, color: COLORS.text } },
      y: { grid: { color: "rgba(0,0,0,0)" }, ticks: { color: COLORS.text } },
    },
    ...extra,
  });
}

function seriesColor(code, fallbackBloc) {
  return COUNTRY_COLORS[code] || blocColor(fallbackBloc) || COLORS.muted;
}

function formatIndexTick(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "";
  if (n >= 1000) {
    const short = n / 1000;
    return `${Number.isInteger(short) ? short.toFixed(0) : short.toFixed(1)}k`;
  }
  return n.toFixed(0);
}

function emptyHTML(id, msg) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = `<div class="empty-state">${escapeHTML(msg)}</div>`;
}

function chartEmpty(id, msg) {
  destroyChart(id);
  const el = document.getElementById(id);
  if (!el) return;
  const parent = el.parentElement;
  if (!parent) return;
  parent.querySelectorAll(".empty-state").forEach(node => node.remove());
  parent.insertAdjacentHTML("beforeend", `<div class="empty-state">${escapeHTML(msg)}</div>`);
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortMoneyB(value) {
  if (value === null || value === undefined || value === "") return "--";
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}T`;
  if (Math.abs(n) >= 100) return `$${n.toFixed(0)}B`;
  if (Math.abs(n) >= 10) return `$${n.toFixed(1)}B`;
  return `$${n.toFixed(2)}B`;
}

function numericOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function fmtPct(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "--";
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : "--";
}

function fmtPlain(value, digits = 1) {
  if (value === null || value === undefined || value === "") return "--";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : "--";
}

function fmtNumber(value, digits = 0) {
  if (value === null || value === undefined || value === "") return "--";
  const n = Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits })
    : "--";
}

function metricValue(row, metric) {
  if (!row) return null;
  return row.value == null ? null : Number(row.value);
}

function blocColor(bloc) {
  return COLORS[bloc] || COLORS.muted;
}

function loadWorld() {
  if (!worldPromise) {
    worldPromise = d3
      .json("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json")
      .then(world => topojson.feature(world, world.objects.countries).features);
  }
  return worldPromise;
}

async function renderMap(rows, state, metricMeta, version) {
  const svg = d3.select("#map-svg");
  const tooltip = d3.select("#map-tooltip");
  const legendRoot = d3.select(".map-legend");
  tooltip.style("opacity", 0);
  legendRoot.selectAll(".scale-legend").remove();
  svg.selectAll("*").remove();

  if (!rows || !rows.length) {
    svg.append("text")
      .attr("x", 260)
      .attr("y", 210)
      .attr("fill", COLORS.muted)
      .attr("text-anchor", "middle")
      .text("No map data");
    return;
  }

  const world = await loadWorld();
  if (version != null && version !== state.loadVersion) return;
  const rowByIso = new Map(rows.map(row => [row.country_iso3, row]));
  const targetIds = new Set(Object.keys(COUNTRY_NUMERIC_TO_ISO));

  const projectFeatures = world.filter(f => targetIds.has(String(f.id)));
  const neighborFeatures = world.filter(f => NEIGHBOR_NUMERIC.has(String(f.id)));
  const cpvPoint = {
    type: "Feature",
    id: "132-point",
    properties: { iso: "CPV" },
    geometry: { type: "Point", coordinates: [-23.62, 15.12] },
  };
  const fitFeatures = rowByIso.has("CPV")
    ? projectFeatures.concat([cpvPoint])
    : projectFeatures;

  const projection = d3.geoMercator().fitExtent(
    [[18, 18], [502, 402]],
    { type: "FeatureCollection", features: fitFeatures }
  );
  const path = d3.geoPath(projection);
  const values = rows
    .map(row => Number(row.value))
    .filter(Number.isFinite);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 1;
  const colorScale = (values.length && new Set(values).size > 1)
    ? d3.scaleQuantile().domain(values).range(COLORS.teal)
    : d3.scaleQuantize().domain([min - 1, max + 1]).range(COLORS.teal);

  const root = svg.append("g").attr("class", "map-root");

  svg.call(
    d3.zoom()
      .scaleExtent([1, 5])
      .translateExtent([[-80, -80], [600, 500]])
      .on("zoom", event => root.attr("transform", event.transform))
  );

  root.selectAll(".map-neighbor")
    .data(neighborFeatures)
    .join("path")
    .attr("class", "map-neighbor")
    .attr("d", path);

  root.selectAll(".map-country")
    .data(projectFeatures)
    .join("path")
    .attr("class", "map-country")
    .attr("data-iso", feature => COUNTRY_NUMERIC_TO_ISO[String(feature.id)])
    .attr("aria-label", feature => COUNTRY_NUMERIC_TO_ISO[String(feature.id)])
    .attr("d", path)
    .attr("fill", feature => {
      const iso = COUNTRY_NUMERIC_TO_ISO[String(feature.id)];
      const row = rowByIso.get(iso);
      const value = metricValue(row, state.mapMetric);
      return Number.isFinite(value) ? colorScale(value) : "#20211e";
    })
    .attr("stroke", feature => {
      const iso = COUNTRY_NUMERIC_TO_ISO[String(feature.id)];
      return blocColor(rowByIso.get(iso)?.analytical_bloc_code);
    })
    .attr("stroke-width", feature => {
      const iso = COUNTRY_NUMERIC_TO_ISO[String(feature.id)];
      if (state.country === iso) return 3;
      return rowByIso.get(iso)?.analytical_bloc_code === state.bloc ? 1.6 : 0.65;
    })
    .attr("opacity", feature => {
      const iso = COUNTRY_NUMERIC_TO_ISO[String(feature.id)];
      if (!state.country) return 1;
      return state.country === iso ? 1 : 0.48;
    })
    .on("mousemove", (event, feature) => {
      const iso = COUNTRY_NUMERIC_TO_ISO[String(feature.id)];
      const row = rowByIso.get(iso);
      const val = metricValue(row, state.mapMetric);
      const svgRect = svg.node().getBoundingClientRect();
      tooltip
        .style("opacity", 1)
        .style("left", `${event.clientX - svgRect.left}px`)
        .style("top", `${event.clientY - svgRect.top}px`)
        .html(
          `<b>${escapeHTML(row?.country_name || iso)}</b><br>` +
          `<span class="muted">${escapeHTML(row?.analytical_bloc_code || "")}</span><br>` +
          `${escapeHTML(metricMeta.label)}: <b>${metricMeta.format(val)}</b>`
        );
    })
    .on("mouseleave", () => tooltip.style("opacity", 0))
    .on("click", (_event, feature) => {
      const iso = COUNTRY_NUMERIC_TO_ISO[String(feature.id)];
      if (window.dashboardSelectCountry) window.dashboardSelectCountry(iso);
    });

  root.selectAll(".map-label")
    .data(projectFeatures)
    .join("text")
    .attr("class", "map-label")
    .attr("transform", feature => {
      const point = path.centroid(feature);
      return `translate(${point[0]},${point[1]})`;
    })
    .text(feature => COUNTRY_NUMERIC_TO_ISO[String(feature.id)]);

  if (rowByIso.has("CPV")) {
    const cpvRow = rowByIso.get("CPV");
    const [cx, cy] = projection(cpvPoint.geometry.coordinates);
    root.append("circle")
      .attr("class", "map-country map-point")
      .attr("data-iso", "CPV")
      .attr("aria-label", "CPV")
      .attr("cx", cx)
      .attr("cy", cy)
      .attr("r", state.country === "CPV" ? 5 : 4)
      .attr("fill", Number.isFinite(metricValue(cpvRow, state.mapMetric)) ? colorScale(metricValue(cpvRow, state.mapMetric)) : "#20211e")
      .attr("stroke", blocColor(cpvRow?.analytical_bloc_code))
      .attr("stroke-width", state.country === "CPV" ? 2.5 : 1.4)
      .on("mousemove", event => {
        const val = metricValue(cpvRow, state.mapMetric);
        const svgRect = svg.node().getBoundingClientRect();
        tooltip
          .style("opacity", 1)
          .style("left", `${event.clientX - svgRect.left}px`)
          .style("top", `${event.clientY - svgRect.top}px`)
          .html(
            `<b>${escapeHTML(cpvRow?.country_name || "Cabo Verde")}</b><br>` +
            `<span class="muted">${escapeHTML(cpvRow?.analytical_bloc_code || "")}</span><br>` +
            `${escapeHTML(metricMeta.label)}: <b>${metricMeta.format(val)}</b>`
          );
      })
      .on("mouseleave", () => tooltip.style("opacity", 0))
      .on("click", () => {
        if (window.dashboardSelectCountry) window.dashboardSelectCountry("CPV");
      });

    root.append("text")
      .attr("class", "map-label")
      .attr("x", cx)
      .attr("y", cy - 8)
      .text("CPV");
  }

  const scaleLegend = legendRoot.append("div")
    .attr("class", "scale-legend")
    .style("display", "flex")
    .style("align-items", "center")
    .style("gap", "6px")
    .style("font-size", "11px")
    .style("color", COLORS.muted);
  scaleLegend.append("span").text(metricMeta.format(min));
  const swatches = scaleLegend.append("div").style("display", "flex");
  COLORS.teal.forEach(color => {
    swatches.append("i")
      .style("display", "inline-block")
      .style("width", "22px")
      .style("height", "8px")
      .style("background", color);
  });
  scaleLegend.append("span").text(metricMeta.format(max));
  scaleLegend.append("span")
    .style("opacity", "0.7")
    .style("margin-left", "4px")
    .text(`· ${metricMeta.label}`);
}

function partnerLabel(code, sourceName) {
  return ISO3_NAMES[code] || sourceName || code;
}

// Partner bars: imports left, exports right; share is always of World total trade.
function renderPartnerBars(rows, scopeTotalB) {
  const el = document.getElementById("partner-bars");
  if (!el) return;
  if (!rows || !rows.length) {
    emptyHTML("partner-bars", "No named-partner data for this selection.");
    return;
  }
  const top10 = rows.slice(0, 10);
  const maxSide = Math.max(
    ...top10.map(r => Math.max(Number(r.exports_billions_usd) || 0, Number(r.imports_billions_usd) || 0)),
    1e-9
  );
  el.innerHTML = top10.map(row => {
    const exp = Number(row.exports_billions_usd) || 0;
    const imp = Number(row.imports_billions_usd) || 0;
    const balance = exp - imp;
    const share = row.share_of_world_total_pct;
    const expPct = Math.max(1.5, (exp / maxSide) * 100).toFixed(2);
    const impPct = Math.max(1.5, (imp / maxSide) * 100).toFixed(2);
    const tol = Math.max(0.0005, (scopeTotalB || 0) * 0.001);
    const balClass = balance > tol ? "surplus" : balance < -tol ? "deficit" : "balanced";
    const balLabel = Math.abs(balance) < tol ? "≈0" : (balance > 0 ? "+" : "") + shortMoneyB(balance);
    const name = escapeHTML(partnerLabel(row.counterpart_code, row.counterpart_name));
    const flags = [
      row.counterpart_in_same_bloc ? "member of this bloc" : null,
      row.counterpart_historical_or_combined ? "former/combined economy" : null,
    ].filter(Boolean).join(", ");
    return `
      <div class="dbar-row" title="${name}${flags ? ` (${escapeHTML(flags)})` : ""} · balance ${balLabel} · ${fmtPct(share)} of World total trade">
        <div class="dbar-imp-val">${shortMoneyB(imp)}</div>
        <div class="dbar-imp-track"><div class="dbar-imp-fill" style="width:${impPct}%"></div></div>
        <div class="dbar-center">
          <span class="dbar-name">${name}${row.counterpart_in_same_bloc ? ' <span class="tag">member</span>' : ""}</span>
          <span class="dbar-meta"><span class="dbar-bal ${balClass}">${balLabel}</span><span class="dbar-sep">·</span>${fmtPct(share)}</span>
        </div>
        <div class="dbar-exp-track"><div class="dbar-exp-fill" style="width:${expPct}%"></div></div>
        <div class="dbar-exp-val">${shortMoneyB(exp)}</div>
      </div>`;
  }).join("");
}

function yearMarker(years, selectedYear) {
  return {
    id: "selectedYearMarker",
    afterDraw(chart) {
      const idx = years.indexOf(Number(selectedYear));
      if (idx < 0) return;
      const x = chart.scales.x.getPixelForValue(idx);
      const { top, bottom } = chart.chartArea;
      const c = chart.ctx;
      c.save();
      c.setLineDash([4, 3]);
      c.strokeStyle = "rgba(255,255,255,0.35)";
      c.lineWidth = 1.2;
      c.beginPath();
      c.moveTo(x, top);
      c.lineTo(x, bottom);
      c.stroke();
      c.restore();
    },
  };
}

/**
 * Generic multi-series line chart.
 * series: [{label, color, values: (number|null)[], width?, dash?}]
 */
function breakMarker(years, breakYear, label) {
  return {
    id: "compositionBreakMarker",
    afterDraw(chart) {
      const idx = years.indexOf(Number(breakYear));
      if (idx < 0) return;
      const x = chart.scales.x.getPixelForValue(idx);
      const { top, bottom } = chart.chartArea;
      const c = chart.ctx;
      c.save();
      c.setLineDash([2, 3]);
      c.strokeStyle = COLORS.AES;
      c.lineWidth = 1.4;
      c.beginPath();
      c.moveTo(x, top);
      c.lineTo(x, bottom);
      c.stroke();
      c.setLineDash([]);
      c.fillStyle = COLORS.AES;
      c.font = "10px " + Chart.defaults.font.family;
      c.textAlign = "right";
      c.fillText(label, x - 4, top + 10);
      c.restore();
    },
  };
}

function renderLines(id, years, series, { title = "", yTitle = "", format = v => fmtPlain(v, 1), selectedYear = null, log = false, yMin, breakYear = null, breakLabel = "membership break" } = {}) {
  const ctx = canvas(id);
  if (!ctx) return;
  const any = series.some(s => s.values.some(v => v != null));
  if (!years.length || !any) return chartEmpty(id, "No observations for this selection.");
  const opts = lineOptions(title, yTitle, {
    plugins: {
      legend: { position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 3, usePointStyle: true, pointStyle: "line" } },
      title: { display: !!title, text: title, color: COLORS.text, font: { size: 12, weight: "500" } },
      tooltip: {
        backgroundColor: "#11120f", borderColor: "#55564f", borderWidth: 1,
        callbacks: {
          title: items => items.length ? `${items[0].label}` : "",
          label: item => `${item.dataset.label}: ${item.parsed.y == null ? "no data" : format(item.parsed.y)}`,
        },
      },
    },
  });
  if (log) {
    opts.scales.y.type = "logarithmic";
    opts.scales.y.ticks.callback = value => formatIndexTick(value);
  } else if (yMin !== undefined) {
    opts.scales.y.min = yMin;
  }
  chartStore[id] = new Chart(ctx, {
    type: "line",
    data: {
      labels: years,
      datasets: series.map(s => ({
        label: s.label,
        data: s.values,
        borderColor: s.color,
        backgroundColor: s.color,
        borderWidth: s.width ?? 2,
        borderDash: s.dash || [],
        // Isolated observations (no neighbours) get a visible point so a
        // single-year series, such as the 2024 AES cohort, is not invisible.
        pointRadius: s.values.map((v, i) => (v != null && s.values[i - 1] == null && s.values[i + 1] == null) ? 3.5 : 0),
        pointHoverRadius: 4,
        tension: 0.2,
        spanGaps: false,
      })),
    },
    options: opts,
    plugins: [
      ...(selectedYear != null ? [yearMarker(years, selectedYear)] : []),
      ...(breakYear != null ? [breakMarker(years, breakYear, `${breakYear} ${breakLabel}`)] : []),
    ],
  });
}

/**
 * Horizontal grouped/stacked bars.
 * datasets: [{label, color, values}]
 */
function renderBars(id, labels, datasets, { title = "", xTitle = "", stacked = false, format = v => fmtNumber(v, 0) } = {}) {
  const ctx = canvas(id);
  if (!ctx) return;
  if (!labels.length) return chartEmpty(id, "No observations for this selection.");
  const opts = barOptions(title, xTitle, {
    plugins: {
      legend: { position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 8 } },
      title: { display: !!title, text: title, color: COLORS.text, font: { size: 12, weight: "500" } },
      tooltip: {
        backgroundColor: "#11120f", borderColor: "#55564f", borderWidth: 1,
        callbacks: { label: item => `${item.dataset.label}: ${format(item.parsed.x)}` },
      },
    },
  });
  if (stacked) {
    opts.scales.x.stacked = true;
    opts.scales.y.stacked = true;
  }
  chartStore[id] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: datasets.map(d => ({
        label: d.label,
        data: d.values,
        backgroundColor: d.color,
        borderColor: d.color,
        borderWidth: 0,
        barThickness: "flex",
        maxBarThickness: 18,
      })),
    },
    options: opts,
  });
}
