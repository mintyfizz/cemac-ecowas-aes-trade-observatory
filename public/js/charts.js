/**
 * Chart and map renderers for the CEMAC-ECOWAS-AES dashboard.
 * The visual model follows the supplied HTML prototype: D3 map + Chart.js.
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
  if (parent) parent.insertAdjacentHTML("beforeend", `<div class="empty-state">${escapeHTML(msg)}</div>`);
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

function hhiDescription(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "no concentration score";
  if (n < 0.15) return "diversified";
  if (n <= 0.25) return "moderately concentrated";
  return "highly concentrated";
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

async function renderMap(rows, state, metricMeta) {
  const svg = d3.select("#map-svg");
  const tooltip = d3.select("#map-tooltip");
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
  const scale = d3.scaleQuantize()
    .domain(min === max ? [min - 1, max + 1] : [min, max])
    .range(COLORS.teal);

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
      return Number.isFinite(value) ? scale(value) : "#20211e";
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
      .attr("fill", Number.isFinite(metricValue(cpvRow, state.mapMetric)) ? scale(metricValue(cpvRow, state.mapMetric)) : "#20211e")
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
}

function renderPartnerBars(rows) {
  const el = document.getElementById("partner-bars");
  if (!el) return;
  if (!rows || !rows.length) {
    emptyHTML("partner-bars", "No partner data for this selection.");
    return;
  }

  const max = Math.max(...rows.map(row => Number(row.total_trade_billions_usd) || 0), 1);
  el.innerHTML = rows.slice(0, 10).map(row => {
    const exports = Number(row.exports_billions_usd) || 0;
    const imports = Number(row.imports_billions_usd) || 0;
    const total = Math.max(exports + imports, 0.000001);
    const width = Math.max(3, (Number(row.total_trade_billions_usd || 0) / max) * 100);
    const expWidth = Math.max(0, (exports / total) * width);
    const impWidth = Math.max(0, (imports / total) * width);
    return `
      <div class="bar-row" title="${escapeHTML(row.counterpart_name || row.counterpart_iso3)}">
        <div class="bar-name">${escapeHTML(row.counterpart_name || row.counterpart_iso3)}</div>
        <div class="bar-track">
          <div class="bar-export" style="width:${expWidth}%"></div>
          <div class="bar-import" style="width:${impWidth}%"></div>
        </div>
        <div class="bar-value">${shortMoneyB(row.total_trade_billions_usd)}</div>
      </div>`;
  }).join("");
}

function renderPartnerTrend(rows, p1, p2) {
  const ctx = canvas("partner-trend");
  if (!ctx) return;
  if (!rows || !rows.length) return chartEmpty("partner-trend", "Select two partners with time-series coverage.");

  const years = [...new Set(rows.map(row => row.year))].sort((a, b) => a - b);
  const dataFor = iso => years.map(year => {
    const found = rows.find(row => row.year === year && row.counterpart_iso3 === iso);
    return found ? found.share_pct : null;
  });

  chartStore["partner-trend"] = new Chart(ctx, {
    type: "line",
    data: {
      labels: years,
      datasets: [
        { label: p1, data: dataFor(p1), borderColor: COLORS.exports, backgroundColor: COLORS.exports, tension: 0.25, spanGaps: true, pointRadius: 2 },
        { label: p2, data: dataFor(p2), borderColor: COLORS.imports, backgroundColor: COLORS.imports, tension: 0.25, spanGaps: true, pointRadius: 2 },
      ],
    },
    options: lineOptions("Partner share of total trade (%)", "Share (%)"),
  });
}

function renderHHI(data, state) {
  const ctx = canvas("hhi-chart");
  if (!ctx) return;
  const rows = data?.hhi || [];
  if (!rows.length) return chartEmpty("hhi-chart", "No HHI data.");

  if (state.country) {
    // rows is the country's own HHI time-series across all years (API fixed)
    const years = [...new Set(rows.map(row => row.year))].sort((a, b) => a - b);
    const name = rows[0]?.country_name || state.country;
    chartStore["hhi-chart"] = new Chart(ctx, {
      type: "line",
      data: {
        labels: years,
        datasets: [
          {
            label: name,
            data: years.map(year => rows.find(row => row.year === year)?.hhi ?? null),
            borderColor: COLORS.exports,
            backgroundColor: COLORS.exports,
            pointRadius: 0,
            pointHoverRadius: 4,
            tension: 0.24,
            spanGaps: true,
          },
          {
            label: "Highly concentrated (0.25)",
            data: years.map(() => 0.25),
            borderColor: COLORS.danger,
            borderDash: [4, 4],
            pointRadius: 0,
            borderWidth: 1.2,
          },
          {
            label: "Diversified threshold (0.15)",
            data: years.map(() => 0.15),
            borderColor: "#7ed66d",
            borderDash: [3, 3],
            pointRadius: 0,
            borderWidth: 1,
          },
        ],
      },
      options: lineOptions("Partner HHI over time", "HHI"),
    });
    return;
  }

  const blocs = [...new Set(rows.map(row => row.analytical_bloc_code))].sort();
  const years = [...new Set(rows.map(row => row.year))].sort((a, b) => a - b);
  chartStore["hhi-chart"] = new Chart(ctx, {
    type: "line",
    data: {
      labels: years,
      datasets: blocs.map(bloc => ({
        label: bloc,
        data: years.map(year => rows.find(row => row.year === year && row.analytical_bloc_code === bloc)?.hhi ?? null),
        borderColor: blocColor(bloc),
        backgroundColor: blocColor(bloc),
        borderWidth: bloc === state.bloc ? 2.6 : 1.2,
        pointRadius: 0,
        tension: 0.24,
        spanGaps: true,
      })).concat([
        {
          label: "Highly concentrated (0.25)",
          data: years.map(() => 0.25),
          borderColor: COLORS.danger,
          borderDash: [4, 4],
          pointRadius: 0,
          borderWidth: 1.2,
        },
        {
          label: "Diversified threshold (0.15)",
          data: years.map(() => 0.15),
          borderColor: "#7ed66d",
          borderDash: [3, 3],
          pointRadius: 0,
          borderWidth: 1,
        },
      ]),
    },
    options: lineOptions("Partner HHI over time", "HHI"),
  });
}

function renderIntegration(rows, state) {
  const ctx = canvas("integration-chart");
  if (!ctx) return;
  if (!rows || !rows.length) return chartEmpty("integration-chart", "No bloc comparison data.");

  const blocs = [...new Set(rows.map(row => row.analytical_bloc_code))].sort();
  const years = [...new Set(rows.map(row => row.year))].sort((a, b) => a - b);
  chartStore["integration-chart"] = new Chart(ctx, {
    type: "line",
    data: {
      labels: years,
      datasets: blocs.map(bloc => ({
        label: bloc,
        data: years.map(year => rows.find(row => row.year === year && row.analytical_bloc_code === bloc)?.intra_share_pct ?? null),
        borderColor: blocColor(bloc),
        backgroundColor: blocColor(bloc),
        borderWidth: bloc === state.bloc ? 2.6 : 1.2,
        pointRadius: years.map(year => year === state.year ? (bloc === state.bloc ? 4 : 3) : 0),
        pointHoverRadius: 5,
        tension: 0.24,
        spanGaps: true,
      })),
    },
    options: lineOptions("Trade openness proxy (% of GDP)", "Trade / GDP (%)", {
      plugins: {
        legend: { position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 3, usePointStyle: true, pointStyle: "line" } },
        title: { display: true, text: "Trade openness proxy (% of GDP)", color: COLORS.text, font: { size: 12, weight: "500" } },
        tooltip: {
          backgroundColor: "#11120f",
          borderColor: "#55564f",
          borderWidth: 1,
          callbacks: {
            title: items => items.length ? `Year ${items[0].label}` : "",
            label: item => `${item.dataset.label}: ${fmtPct(item.parsed.y)}`,
          },
        },
      },
    }),
  });
}

function renderGrowth(rows, state) {
  const ctx = canvas("growth-chart");
  if (!ctx) return;
  if (!rows || !rows.length) return chartEmpty("growth-chart", "No growth data.");

  const years = [...new Set(rows.map(row => row.year))].sort((a, b) => a - b);
  const groups = [...new Set(rows.map(row => row.series_code || row.country_iso3 || row.analytical_bloc_code))];
  const rowBySeriesYear = new Map(rows.map(row => [`${row.series_code || row.country_iso3 || row.analytical_bloc_code}:${row.year}`, row]));
  const values = rows.map(row => Number(row.index_value)).filter(Number.isFinite);
  const maxIndex = values.length ? Math.max(...values) : 0;
  const minIndex = values.length ? Math.min(...values.filter(value => value > 0)) : 100;
  const useLogScale = maxIndex > 1500 && minIndex > 0;
  const yTitle = useLogScale ? "Index (1990=100, log scale)" : "Index (1990=100)";
  const logTicks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];
  const logMax = logTicks.find(value => value >= maxIndex) || Math.ceil(maxIndex / 10000) * 10000;

  chartStore["growth-chart"] = new Chart(ctx, {
    type: "line",
    data: {
      labels: years,
      datasets: groups.map(code => {
        const first = rows.find(row => (row.series_code || row.country_iso3 || row.analytical_bloc_code) === code);
        const bloc = first?.analytical_bloc_code || code;
        const selected = state.country ? code === state.country : true;
        const color = seriesColor(code, bloc);
        return {
          label: first?.series_name || first?.country_name || code,
          data: years.map(year => rowBySeriesYear.get(`${code}:${year}`)?.index_value ?? null),
          borderColor: color,
          backgroundColor: color,
          borderWidth: selected ? 2.35 : 1.4,
          pointRadius: 0,
          pointHitRadius: 14,
          pointHoverRadius: 4.5,
          pointHoverBorderWidth: 2,
          tension: 0.18,
          spanGaps: true,
        };
      }).concat([{
        label: "1990 baseline",
        data: years.map(() => 100),
        borderColor: COLORS.muted,
        borderDash: [3, 4],
        borderWidth: 1,
        pointRadius: 0,
        pointHitRadius: 0,
        pointHoverRadius: 0,
      }]),
    },
    options: lineOptions(
      useLogScale ? "Indexed total goods trade growth (log scale)" : "Indexed total goods trade growth",
      yTitle,
      {
        scales: {
          x: { grid: { color: COLORS.grid }, ticks: { color: COLORS.text, maxRotation: 0 } },
          y: {
            type: useLogScale ? "logarithmic" : "linear",
            min: useLogScale ? Math.max(20, logTicks.find(value => value <= minIndex) || 20) : undefined,
            suggestedMin: useLogScale ? undefined : 0,
            suggestedMax: useLogScale ? logMax : undefined,
            afterBuildTicks: useLogScale
              ? axis => {
                  axis.ticks = logTicks
                    .filter(value => value >= axis.min && value <= axis.max)
                    .map(value => ({ value }));
                }
              : undefined,
            grid: { color: COLORS.grid },
            ticks: {
              color: COLORS.text,
              padding: 6,
              maxTicksLimit: useLogScale ? 9 : 6,
              callback: value => useLogScale ? formatIndexTick(value) : fmtPlain(value, 0),
            },
            title: { display: true, text: yTitle, color: COLORS.text },
          },
        },
        interaction: { mode: "nearest", axis: "xy", intersect: false },
        hover: { mode: "nearest", intersect: false },
        plugins: {
          legend: { position: "top", align: "end", labels: { boxWidth: 11, boxHeight: 3, usePointStyle: true, pointStyle: "line" } },
          title: { display: true, text: useLogScale ? "Indexed total trade growth (log scale)" : "Indexed total trade growth", color: COLORS.text, font: { size: 12, weight: "500" } },
          tooltip: {
            mode: "nearest",
            intersect: false,
            axis: "xy",
            backgroundColor: "#11120f",
            borderColor: "#55564f",
            borderWidth: 1,
            displayColors: true,
            filter: item => item.dataset.label !== "1990 baseline",
            callbacks: {
              title: items => items.length ? `Year ${items[0].label}` : "",
              label: item => {
                const code = groups[item.datasetIndex];
                const row = rowBySeriesYear.get(`${code}:${item.label}`);
                const index = Number(row?.index_value);
                const multiple = Number.isFinite(index) ? index / 100 : null;
                return `${item.dataset.label}: ${fmtNumber(index, 0)} (${fmtPlain(multiple, 1)}x 1990)`;
              },
              afterLabel: item => {
                const code = groups[item.datasetIndex];
                const row = rowBySeriesYear.get(`${code}:${item.label}`);
                return `Trade: ${shortMoneyB(row?.total_trade_billions_usd)}`;
              },
            },
          },
        },
      }
    ),
  });
}

function renderStructureTree(overview) {
  const ctx = canvas("exposure-chart");
  const note = document.getElementById("exposure-note");
  if (!ctx) return;
  ctx.parentElement?.querySelectorAll(".empty-state").forEach(node => node.remove());

  const exportVal = numericOrNull(overview.exports_billions_usd);
  const importVal = numericOrNull(overview.imports_billions_usd);
  const balance = numericOrNull(overview.trade_balance_billions_usd);
  const gdp = numericOrNull(overview.gdp_current_usd_billions);
  const rawExportsPct = numericOrNull(overview.exports_pct_gdp);
  const rawImportsPct = numericOrNull(overview.imports_pct_gdp);
  const exportsPct = rawExportsPct ?? (exportVal != null && gdp ? exportVal / gdp * 100 : null);
  const importsPct = rawImportsPct ?? (importVal != null && gdp ? importVal / gdp * 100 : null);
  const balancePctGdp = balance != null && gdp ? balance / gdp * 100 : null;

  const rows = [
    { label: "Exports / GDP", pct: exportsPct, usd: exportVal, color: COLORS.exports },
    { label: "Imports / GDP", pct: importsPct, usd: importVal, color: COLORS.imports },
    { label: "Balance / GDP", pct: balancePctGdp, usd: balance, color: balance == null || balance >= 0 ? COLORS.exports : COLORS.danger },
  ];
  const validRows = rows.filter(row => Number.isFinite(row.pct));
  if (!validRows.length) {
    if (note) note.textContent = "";
    return chartEmpty("exposure-chart", "No trade exposure data.");
  }

  const minValue = Math.min(0, ...validRows.map(row => row.pct));
  const maxValue = Math.max(0, ...validRows.map(row => row.pct));
  const range = Math.max(maxValue - minValue, 20);
  const axisMin = Math.floor((minValue - range * 0.08) / 10) * 10;
  const axisMax = Math.ceil((maxValue + range * 0.12) / 10) * 10;

  if (note) {
    note.textContent = `Openness = exports + imports: ${fmtPct(overview.trade_openness_pct_gdp)} of GDP. Balance = exports - imports.`;
  }

  chartStore["exposure-chart"] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: validRows.map(row => row.label),
      datasets: [{
        label: "% of GDP",
        data: validRows.map(row => row.pct),
        backgroundColor: validRows.map(row => row.color),
        borderRadius: 6,
        borderSkipped: false,
        barPercentage: 0.68,
        categoryPercentage: 0.7,
        customRows: validRows,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      indexAxis: "y",
      interaction: { mode: "nearest", axis: "y", intersect: false },
      hover: { mode: "nearest", intersect: false },
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: "Trade exposure as share of GDP",
          color: COLORS.text,
          font: { size: 12, weight: "500" },
        },
        tooltip: {
          backgroundColor: "#11120f",
          borderColor: "#55564f",
          borderWidth: 1,
          displayColors: false,
          callbacks: {
            title: items => items.length ? items[0].label : "",
            label: item => `${fmtPct(item.parsed.x)} of GDP`,
            afterLabel: item => {
              const row = item.dataset.customRows?.[item.dataIndex];
              return row ? `${shortMoneyB(row.usd)} current USD` : "";
            },
          },
        },
      },
      scales: {
        x: {
          min: axisMin,
          max: axisMax,
          grid: { color: COLORS.grid },
          ticks: { color: COLORS.text, callback: value => `${value}%` },
          title: { display: true, text: "% of GDP", color: COLORS.text },
        },
        y: {
          grid: { color: "rgba(0,0,0,0)" },
          ticks: { color: COLORS.text },
        },
      },
    },
  });
}

function renderConflict(rows) {
  const ctx = canvas("conflict-chart");
  if (!ctx) return;
  if (!rows || !rows.length) return chartEmpty("conflict-chart", "No ACLED hotspot data.");
  const selected = [...rows].sort((a, b) => (b.violent_events || 0) - (a.violent_events || 0)).slice(0, 10).reverse();
  chartStore["conflict-chart"] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: selected.map(row => row.admin1 || row.country_name || row.country_iso3),
      datasets: [
        { label: "Violent events", data: selected.map(row => row.violent_events || 0), backgroundColor: "#d9c875" },
        { label: "Fatalities", data: selected.map(row => row.fatalities || 0), backgroundColor: "#d87b8a" },
      ],
    },
    options: barOptions("Conflict events & fatalities", "Count"),
  });
}

function renderFragility(rows) {
  const ctx = canvas("fragility-chart");
  if (!ctx) return;
  if (!rows || !rows.length) return chartEmpty("fragility-chart", "No FSI data.");

  const labels = ["Cohesion", "Economic", "Political", "Social"];
  if (rows.length === 1) {
    const row = rows[0];
    chartStore["fragility-chart"] = new Chart(ctx, {
      type: "radar",
      data: {
        labels,
        datasets: [{
          label: row.country_name || row.country_iso3,
          data: [row.cohesion_score, row.economic_score, row.political_score, row.social_cross_cutting_score],
          borderColor: COLORS.imports,
          backgroundColor: "rgba(127,119,221,0.22)",
          pointBackgroundColor: COLORS.imports,
        }],
      },
      options: radarOptions("Fragility components (latest FSI)", 30),
    });
    return;
  }

  const top = [...rows].sort((a, b) => (b.fsi_total_score || 0) - (a.fsi_total_score || 0)).slice(0, 8).reverse();
  chartStore["fragility-chart"] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: top.map(row => row.country_iso3),
      datasets: [
        { label: "Cohesion", data: top.map(row => row.cohesion_score || 0), backgroundColor: COLORS.danger },
        { label: "Economic", data: top.map(row => row.economic_score || 0), backgroundColor: COLORS.warning },
        { label: "Political", data: top.map(row => row.political_score || 0), backgroundColor: COLORS.imports },
        { label: "Social", data: top.map(row => row.social_cross_cutting_score || 0), backgroundColor: COLORS.exports },
      ],
    },
    options: barOptions("Fragility components (latest FSI)", "Score"),
  });
}

function radarOptions(title, max) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: "top", align: "end", labels: { boxWidth: 10, boxHeight: 3 } },
      title: { display: !!title, text: title, color: COLORS.text, font: { size: 12, weight: "500" } },
      tooltip: { backgroundColor: "#11120f", borderColor: "#55564f", borderWidth: 1 },
    },
    scales: {
      r: {
        suggestedMin: 0,
        suggestedMax: max,
        angleLines: { color: COLORS.grid },
        grid: { color: COLORS.grid },
        pointLabels: { color: COLORS.text },
        ticks: { color: COLORS.muted, backdropColor: "transparent" },
      },
    },
  };
}

function renderRiskRadar(scores, label) {
  const ctx = canvas("risk-chart");
  if (!ctx) return;
  const rows = Array.isArray(scores) ? scores : [];
  if (!rows.length) return chartEmpty("risk-chart", "No pressure-score data.");
  chartStore["risk-chart"] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: rows.map(row => row.label),
      datasets: [{
        label,
        data: rows.map(row => row.score ?? null),
        backgroundColor: rows.map(row => {
          const score = Number(row.score);
          if (!Number.isFinite(score)) return COLORS.grid;
          if (score >= 70) return COLORS.danger;
          if (score >= 40) return COLORS.warning;
          return COLORS.exports;
        }),
        borderWidth: 0,
      }],
    },
    options: barOptions("Pressure score (0-100)", "Normalized pressure", {
      scales: {
        x: {
          min: 0,
          max: 100,
          grid: { color: COLORS.grid },
          ticks: { color: COLORS.text },
          title: { display: true, text: "Higher = more pressure", color: COLORS.text },
        },
        y: { grid: { color: "rgba(0,0,0,0)" }, ticks: { color: COLORS.text } },
      },
      plugins: {
        legend: { display: false },
        title: { display: true, text: "Pressure score (0-100)", color: COLORS.text, font: { size: 12, weight: "500" } },
        tooltip: {
          backgroundColor: "#11120f",
          borderColor: "#55564f",
          borderWidth: 1,
          callbacks: {
            label: item => `Score: ${fmtPlain(item.parsed.x, 0)} / 100`,
            afterLabel: item => {
              const row = rows[item.dataIndex];
              return [`Actual: ${row.actual}`, row.detail].filter(Boolean);
            },
          },
        },
      },
    }),
  });
}

function renderHealth(rows) {
  const el = document.getElementById("health-grid");
  if (!el) return;
  if (!rows || !rows.length) {
    el.innerHTML = `<div class="empty-state">No coverage summary available.</div>`;
    return;
  }
  el.innerHTML = rows.map(row => `
    <div class="health-card">
      <div class="lbl">${escapeHTML(row.label)}</div>
      <div class="val">${escapeHTML(row.value)}</div>
      <div class="desc">${escapeHTML(row.description)}</div>
    </div>
  `).join("");
}

function renderProducts(rows, flow) {
  const el = canvas("products-chart");
  if (!el) return;

  const top = rows.slice(0, 12);
  const color = flow === "export" ? COLORS.exports : COLORS.imports;
  const barColor = color + "cc";
  const borderColor = color;

  const labels = top.map(r => {
    const desc = r.hs2_description || `HS ${r.hs2_code}`;
    const label = `HS ${r.hs2_code} · ${desc}`;
    return label.length > 54 ? label.slice(0, 51) + "…" : label;
  });
  const values = top.map(r => numericOrNull(r.trade_value_billions_usd));
  const shares = top.map(r => numericOrNull(r.hs2_share_pct));
  const codes  = top.map(r => r.hs2_code);
  const descs  = top.map(r => r.hs2_description || `HS ${r.hs2_code}`);

  chartStore["products-chart"] = new Chart(el, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: barColor,
        borderColor,
        borderWidth: 1,
        borderRadius: 3,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", axis: "y", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#11120f",
          borderColor: "#55564f",
          borderWidth: 1,
          callbacks: {
            title: ctx => `HS ${codes[ctx[0].dataIndex]}: ${descs[ctx[0].dataIndex]}`,
            label: ctx => {
              const val = ctx.parsed.x;
              const share = shares[ctx.dataIndex];
              return `Trade value: ${shortMoneyB(val)}`;
            },
            afterLabel: ctx => `Share of ${flow}s: ${fmtPct(shares[ctx.dataIndex])}`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(255,255,255,0.06)" },
          ticks: {
            color: "#aaa",
            font: { size: 11 },
            callback: value => `$${value}B`,
          },
        },
        y: {
          grid: { display: false },
          ticks: { color: "#ccc", font: { size: 11 } },
        },
      },
    },
  });
}
