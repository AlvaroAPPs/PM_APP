const $ = (id) => document.getElementById(id);

const MAX_CHART_POINTS = 25;
const DEFAULT_TOTAL_HOURS = null;
let activeProjectCode = null;
let activeTotalHours = DEFAULT_TOTAL_HOURS;
const STATUS_CLASSES = {
  red: "status-red",
  amber: "status-amber",
  green: "status-green",
  orange: "status-orange",
};

const PHASES = [
  { key: "date_kickoff", label: "Kick-off" },
  { key: "date_design", label: "Design" },
  { key: "date_validation", label: "Validation" },
  { key: "date_golive", label: "Go-live" },
  { key: "date_reception", label: "Reception" },
  { key: "date_end", label: "End" },
];

function setIndicator(idPrefix, status, label, detail) {
  const card = $(`indicator-${idPrefix}`);
  const badge = $(`indicator-${idPrefix}-status`);
  const labelEl = $(`indicator-${idPrefix}-label`);
  const detailEl = $(`indicator-${idPrefix}-detail`);
  if (!card || !badge || !labelEl || !detailEl) return;
  card.classList.remove(...Object.values(STATUS_CLASSES));
  if (STATUS_CLASSES[status]) {
    card.classList.add(STATUS_CLASSES[status]);
  }
  badge.textContent = status.toUpperCase();
  badge.className = `badge indicator-badge ${
    status === "red"
      ? "text-bg-danger"
      : status === "amber"
      ? "text-bg-warning"
      : status === "green"
      ? "text-bg-success"
      : "text-bg-secondary"
  }`;
  labelEl.textContent = label;
  detailEl.textContent = detail;
}

function formatWeekLabel(year, week) {
  return `${year}-W${String(week).padStart(2, "0")}`;
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatNumber(value, decimals = 2) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString("es-ES", { maximumFractionDigits: decimals })
    : "—";
}

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString("es-ES");
}

function formatInt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `${Math.round(value)}`;
}

function windowSeries(series, maxPoints = MAX_CHART_POINTS) {
  if (series.length <= maxPoints) return series;
  return series.slice(series.length - maxPoints);
}

function calculateDomain(values) {
  const cleanValues = values.filter((value) => Number.isFinite(value));
  if (!cleanValues.length) return null;
  let min = Math.min(...cleanValues);
  let max = Math.max(...cleanValues);
  if (min === max) {
    const pad = min === 0 ? 1 : Math.abs(min * 0.05);
    return { min: min - pad, max: max + pad };
  }
  const pad = (max - min) * 0.05;
  return { min: min - pad, max: max + pad };
}

function isLikelyCumulative(values) {
  if (values.length < 3) return false;
  let nonDecreasing = 0;
  let negative = 0;
  let diffs = [];
  for (let i = 1; i < values.length; i += 1) {
    const prev = values[i - 1];
    const curr = values[i];
    if (!Number.isFinite(prev) || !Number.isFinite(curr)) continue;
    const diff = curr - prev;
    diffs.push(Math.abs(diff));
    if (diff >= 0) nonDecreasing += 1;
    if (diff < 0) negative += 1;
  }
  const effectiveDiffs = diffs.length || 1;
  const avgDiff = diffs.reduce((sum, v) => sum + v, 0) / effectiveDiffs;
  const last = values[values.length - 1];
  const first = values[0];
  const mostlyNonDecreasing = negative <= Math.max(1, Math.floor(effectiveDiffs * 0.2));
  return mostlyNonDecreasing && Number.isFinite(last) && Number.isFinite(first) && last >= first && last >= avgDiff * 2;
}

function toDeltaSeries(values) {
  if (!values.length) return [];
  return values.map((value, index) => {
    if (!Number.isFinite(value)) return null;
    if (index === 0) return value;
    const prev = values[index - 1];
    if (!Number.isFinite(prev)) return null;
    return value - prev;
  });
}

function safeWeeklySeries(values) {
  if (!values.length) return [];
  const numericValues = values.map((value) => (Number.isFinite(value) ? value : null));
  if (isLikelyCumulative(numericValues)) {
    return toDeltaSeries(numericValues);
  }
  return numericValues;
}

function sortByWeek(list) {
  return [...list].sort((a, b) => {
    if (a.year !== b.year) return a.year - b.year;
    return a.week - b.week;
  });
}

function addWeek(year, week) {
  let nextWeek = week + 1;
  let nextYear = year;
  if (nextWeek > 52) {
    nextWeek = 1;
    nextYear += 1;
  }
  return [nextYear, nextWeek];
}

function average(values) {
  if (!values.length) return null;
  const total = values.reduce((sum, value) => sum + value, 0);
  return total / values.length;
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

function computeProductivityIndicator(weekly) {
  if (weekly.length < 2) {
    return { status: "green", label: "N/A", detail: "Sin semana anterior" };
  }
  const latest = weekly[weekly.length - 1];
  const prev = weekly[weekly.length - 2];

  const latestReal = toNumber(latest.real_hours);
  const prevReal = toNumber(prev.real_hours);
  const latestTheoretical = toNumber(latest.horas_teoricas);
  const prevTheoretical = toNumber(prev.horas_teoricas);

  if (
    latestReal === null ||
    prevReal === null ||
    latestTheoretical === null ||
    prevTheoretical === null
  ) {
    return { status: "green", label: "N/A", detail: "Datos insuficientes" };
  }

  const gradientReal = latestReal - prevReal;
  const gradientTheoretical = latestTheoretical - prevTheoretical;
  if (gradientTheoretical < gradientReal) {
    return {
      status: "red",
      label: "Alerta",
      detail: "La pendiente teórica es menor que la real",
    };
  }

  return {
    status: "green",
    label: "En control",
    detail: "La pendiente teórica es igual o mayor que la real",
  };
}

function computeDeviationIndicator(weekly) {
  if (!weekly.length) {
    return { status: "green", label: "N/A", detail: "Sin datos" };
  }
  const latest = weekly[weekly.length - 1];

  const latestDev = toNumber(latest.desviacion_pct);
  if (latestDev === null) {
    return { status: "green", label: "N/A", detail: "Datos insuficientes" };
  }
  if (latestDev > 0) {
    return {
      status: "red",
      label: "Alerta",
      detail: `Desviación actual: ${formatNumber(latestDev)}%`,
    };
  }

  return {
    status: "green",
    label: "En control",
    detail: `Desviación actual: ${formatNumber(latestDev)}%`,
  };
}

function computePhaseIndicator(phasesHistory, projectCode) {
  const resetKey = `phaseIndicatorReset:${projectCode}`;
  const resetValue = localStorage.getItem(resetKey);
  if (resetValue === "true") {
    return {
      status: "green",
      label: "Reiniciado",
      detail: "Indicador reiniciado para este proyecto",
      resetKey,
    };
  }

  if (phasesHistory.length < 2) {
    return {
      status: "green",
      label: "N/A",
      detail: "Sin semana anterior",
      resetKey,
    };
  }

  const prev = phasesHistory[phasesHistory.length - 2];
  const curr = phasesHistory[phasesHistory.length - 1];
  const changedPhase = PHASES.find((phase) => (prev[phase.key] || null) !== (curr[phase.key] || null));

  if (changedPhase) {
    return {
      status: "red",
      label: "Cambio detectado",
      detail: `Fase afectada: ${changedPhase.label}`,
      resetKey,
    };
  }

  return {
    status: "green",
    label: "Sin cambios",
    detail: "No hay cambios en fechas",
    resetKey,
  };
}

function renderPhaseChangesTable(phasesHistory) {
  const tbody = $("phaseChangesTable");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (phasesHistory.length < 2) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td colspan="3" class="muted">Sin historial suficiente</td>
    `;
    tbody.appendChild(row);
    return;
  }

  const prev = phasesHistory[phasesHistory.length - 2];
  const curr = phasesHistory[phasesHistory.length - 1];

  PHASES.forEach((phase) => {
    const prevDate = prev[phase.key] || null;
    const currDate = curr[phase.key] || null;
    const changed = (prevDate || currDate) && prevDate !== currDate ? 1 : 0;
    const changeText = `${formatDate(prevDate)} → ${formatDate(currDate)}`;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="fw-semibold">${phase.label}</td>
      <td>${changeText}</td>
      <td>${changed}</td>
    `;
    tbody.appendChild(row);
  });
}

function buildLineChart(ctx, labels, datasetLabel, data, color, domain) {
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: datasetLabel,
          data,
          borderColor: color,
          backgroundColor: color,
          tension: 0.25,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => formatInt(context.parsed.y),
          },
        },
      },
      scales: {
        y: {
          min: domain?.min,
          max: domain?.max,
          ticks: { callback: (value) => formatInt(value) },
        },
      },
    },
  });
}

function buildBarChart(ctx, labels, datasets, domain) {
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        tooltip: {
          callbacks: {
            label: (context) => formatInt(context.parsed.y),
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          min: domain?.min,
          max: domain?.max,
          ticks: { callback: (value) => formatInt(value) },
        },
      },
    },
  });
}

function buildSCurveChart(ctx, actualPoints, pendingPoints, productivityPoints) {
  return new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        {
          label: "Horas reales",
          data: actualPoints,
          borderColor: "#2563eb",
          backgroundColor: "#2563eb",
          tension: 0.25,
          parsing: false,
        },
        {
          label: "Pending Work (no deviation)",
          data: pendingPoints,
          borderColor: "#f97316",
          backgroundColor: "#f97316",
          borderDash: [6, 6],
          tension: 0.25,
          parsing: false,
        },
        {
          label: "Work in productivity",
          data: productivityPoints,
          borderColor: "#7f1d1d",
          backgroundColor: "#7f1d1d",
          borderDash: [6, 6],
          tension: 0.25,
          parsing: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            label: (context) =>
              `${formatInt(context.parsed.x)}%, ${formatInt(context.parsed.y)} h`,
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          title: {
            display: true,
            text: "Progreso (%)",
          },
          ticks: {
            callback: (value) => formatInt(value),
          },
        },
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: "Horas del proyecto",
          },
          ticks: {
            callback: (value) => formatInt(value),
          },
        },
      },
    },
  });
}

function computeTotalProgress(series) {
  let total = 0;
  series.forEach((item) => {
    const value = toNumber(item.progress_w);
    if (value !== null) {
      total = Math.min(100, total + value);
    }
  });
  return total;
}

function buildProjectionForHours(progressWeekly, realCumulative, weekLabels, totalHours) {
  if (!progressWeekly.length || !realCumulative.length) {
    return {
      actualPoints: [],
      pendingPoints: [],
      productivityPoints: [],
      pendingHoursAtClose: null,
      productivityHoursAtClose: null,
      finishingWeekLabel: "N/A",
    };
  }

  const actualPoints = progressWeekly
    .map((value, index) => ({
      x: value,
      y: realCumulative[index],
    }))
    .filter(
      (point) => Number.isFinite(point.x) && Number.isFinite(point.y)
    );

  if (!actualPoints.length) {
    return {
      actualPoints: [],
      pendingPoints: [],
      productivityPoints: [],
      pendingHoursAtClose: null,
      productivityHoursAtClose: null,
      finishingWeekLabel: "N/A",
    };
  }

  const lastPoint = actualPoints[actualPoints.length - 1];
  const latestProgress = lastPoint.x;
  const latestReal = lastPoint.y;

  if (!Number.isFinite(totalHours) || totalHours <= 0) {
    return {
      actualPoints,
      pendingPoints: [],
      productivityPoints: [],
      pendingHoursAtClose: null,
      productivityHoursAtClose: null,
      finishingWeekLabel: "N/A",
    };
  }

  const pendingPercent = Math.max(0, 100 - latestProgress);
  const pendingHours = (pendingPercent / 100) * totalHours;
  const pendingHoursAtClose = latestReal + pendingHours;
  const pendingPoints = [
    { x: latestProgress, y: latestReal },
    { x: 100, y: pendingHoursAtClose },
  ];

  let productivityPoints = [];
  let productivityHoursAtClose = null;
  const progressRatio = latestProgress / 100;
  if (progressRatio > 0) {
    // productivityFactor = realHours / (totalProjectHours * progressRatio)
    const productivityFactor = latestReal / (totalHours * progressRatio);
    const pendingAdjusted = productivityFactor * pendingHours;
    productivityHoursAtClose = latestReal + pendingAdjusted;
    productivityPoints = [
      { x: latestProgress, y: latestReal },
      { x: 100, y: productivityHoursAtClose },
    ];
  }

  const progressDeltas = toDeltaSeries(progressWeekly);
  const positiveDeltas = progressDeltas.filter((value, index) => index > 0 && Number.isFinite(value) && value > 0);
  const avgWeeklyProgress = positiveDeltas.length
    ? positiveDeltas.reduce((sum, v) => sum + v, 0) / positiveDeltas.length
    : null;

  let finishingWeekLabel = "N/A";
  if (avgWeeklyProgress && avgWeeklyProgress > 0) {
    const weeksRemaining = Math.ceil((100 - latestProgress) / avgWeeklyProgress);
    if (weekLabels.length) {
      let [currentYear, currentWeek] = weekLabels[weekLabels.length - 1];
      for (let i = 0; i < weeksRemaining; i += 1) {
        [currentYear, currentWeek] = addWeek(currentYear, currentWeek);
      }
      finishingWeekLabel = formatWeekLabel(currentYear, currentWeek);
    }
  }

  return {
    actualPoints,
    pendingPoints,
    productivityPoints,
    pendingHoursAtClose,
    productivityHoursAtClose,
    finishingWeekLabel,
  };
}

function renderCharts(weekly, totalHours) {
  const visibleWeekly = windowSeries(weekly);
  const labels = visibleWeekly.map((item) =>
    formatWeekLabel(item.year, item.week)
  );
  const progressData = visibleWeekly.map((item) => toNumber(item.progress_w));
  const deviationData = visibleWeekly.map((item) => toNumber(item.desviacion_pct));
  const realHoursRaw = visibleWeekly.map((item) => toNumber(item.real_hours));
  const realHoursDeltaRaw = visibleWeekly.map((item) =>
    toNumber(item.real_hours_delta)
  );
  const theoreticalDeltaRaw = visibleWeekly.map((item) =>
    toNumber(item.horas_teoricas_delta)
  );
  const theoreticalRaw = visibleWeekly.map((item) => toNumber(item.horas_teoricas));
  const realWeeklyHours = realHoursDeltaRaw.every((value) => value !== null)
    ? realHoursDeltaRaw
    : safeWeeklySeries(realHoursRaw);

  const fullProgressCumulative = [];
  let progressTotal = 0;
  weekly.forEach((item) => {
    const progress = toNumber(item.progress_w);
    if (progress !== null) {
      progressTotal = Math.min(100, progressTotal + progress);
    }
    fullProgressCumulative.push(progressTotal);
  });
  const progressCumulative = fullProgressCumulative.slice(
    Math.max(0, fullProgressCumulative.length - visibleWeekly.length)
  );

  const progressDeltas = safeWeeklySeries(progressCumulative);
  const theoreticalWeeklyHours = Number.isFinite(totalHours)
    ? progressDeltas.map((value) =>
        Number.isFinite(value) ? Math.round((value / 100) * totalHours) : null
      )
    : theoreticalDeltaRaw.every((value) => value !== null)
    ? theoreticalDeltaRaw.map((value) =>
        Number.isFinite(value) ? Math.round(value) : null
      )
    : safeWeeklySeries(theoreticalRaw).map((value) =>
        Number.isFinite(value) ? Math.round(value) : null
      );

  const progressDomain = calculateDomain(progressData);
  const deviationDomain = calculateDomain(deviationData);
  const realHoursDomain = calculateDomain(realWeeklyHours);
  const hoursCompareWeekly = visibleWeekly.filter(
    (item) => item.progress_w_delta !== null && item.progress_w_delta !== undefined
  );
  const hoursCompareLabels = hoursCompareWeekly.map((item) =>
    formatWeekLabel(item.year, item.week)
  );
  const hoursCompareReal = hoursCompareWeekly.map((item) => {
    const index = visibleWeekly.indexOf(item);
    return index >= 0 ? realWeeklyHours[index] : null;
  });
  const hoursCompareTheoretical = hoursCompareWeekly.map((item) =>
    toNumber(item.horas_teoricas_delta)
  );
  const hoursCompareDomain = calculateDomain(
    hoursCompareReal.concat(hoursCompareTheoretical)
  );

  buildLineChart(
    $("chartProgress"),
    labels,
    "Progreso semanal",
    progressData.map((value) => (value === null ? null : Math.round(value))),
    "#2563eb",
    progressDomain
  );
  buildLineChart(
    $("chartDeviation"),
    labels,
    "Desviación %",
    deviationData.map((value) => (value === null ? null : Math.round(value))),
    "#dc2626",
    deviationDomain
  );
  buildLineChart(
    $("chartRealHours"),
    labels,
    "Horas reales",
    realWeeklyHours.map((value) =>
      value === null ? null : Math.round(value)
    ),
    "#0ea5e9",
    realHoursDomain
  );

  buildBarChart(
    $("chartHoursCompare"),
    hoursCompareLabels,
    [
      {
        label: "Horas reales",
        data: hoursCompareReal.map((value) =>
          value === null ? null : Math.round(value)
        ),
        backgroundColor: "#1d4ed8",
      },
      {
        label: "Horas teóricas",
        data: hoursCompareTheoretical.map((value) =>
          value === null ? null : Math.round(value)
        ),
        backgroundColor: "#f97316",
      },
    ],
    hoursCompareDomain
  );

  const fullRealCumulative = [];
  const rawCumulative = weekly.map((item) => toNumber(item.real_hours));
  if (isLikelyCumulative(rawCumulative)) {
    rawCumulative.forEach((value) => fullRealCumulative.push(value));
  } else {
    let total = 0;
    const fallbackWeekly = weekly.map((item) => toNumber(item.real_hours_delta));
    const weeklyHours = fallbackWeekly.every((value) => value !== null)
      ? fallbackWeekly
      : safeWeeklySeries(rawCumulative);
    weeklyHours.forEach((value) => {
      if (Number.isFinite(value)) {
        total += value;
      }
      fullRealCumulative.push(total);
    });
  }

  const realCumulative = fullRealCumulative.slice(
    Math.max(0, fullRealCumulative.length - visibleWeekly.length)
  );
  const sCurveProgressWeekly = visibleWeekly.map((item) => toNumber(item.progress_w));
  const sCurveRealCumulative = realCumulative;
  const weekOrder = visibleWeekly.map((item) => [item.year, item.week]);
  const projection = buildProjectionForHours(
    sCurveProgressWeekly,
    sCurveRealCumulative,
    weekOrder,
    totalHours
  );
  buildSCurveChart(
    $("chartSCurve"),
    projection.actualPoints,
    projection.pendingPoints,
    projection.productivityPoints
  );

  const projectionPending = $("projectionHoursPending");
  if (projectionPending) {
    projectionPending.textContent =
      projection.pendingHoursAtClose !== null
        ? `${formatInt(projection.pendingHoursAtClose)} h`
        : "N/A";
  }
  const projectionProductivity = $("projectionHoursProductivity");
  if (projectionProductivity) {
    projectionProductivity.textContent =
      projection.productivityHoursAtClose !== null
        ? `${formatInt(projection.productivityHoursAtClose)} h`
        : "N/A";
  }
  const projectionWeek = $("projectionWeek");
  if (projectionWeek) {
    projectionWeek.textContent = projection.finishingWeekLabel;
  }
}

async function loadIndicators() {
  if (!activeProjectCode) return;
  try {
    const [weeklyRaw, phasesRaw] = await Promise.all([
      fetchJson(`/projects/${encodeURIComponent(activeProjectCode)}/metrics/weekly`),
      fetchJson(`/projects/${encodeURIComponent(activeProjectCode)}/metrics/phases`),
    ]);

    const weekly = sortByWeek(weeklyRaw);
    const phases = sortByWeek(phasesRaw);

    if (!weekly.length || !phases.length) {
      const noData = $("noDataMessage");
      if (noData) noData.classList.remove("d-none");
      return;
    }

    const productivity = computeProductivityIndicator(weekly);
    setIndicator(
      "productivity",
      productivity.status,
      productivity.label,
      productivity.detail
    );
    const deviation = computeDeviationIndicator(weekly);
    setIndicator("deviation", deviation.status, deviation.label, deviation.detail);

    const phaseIndicator = computePhaseIndicator(phases, activeProjectCode);
    setIndicator(
      "phases",
      phaseIndicator.status,
      phaseIndicator.label,
      phaseIndicator.detail
    );

    const resetBtn = $("phaseResetBtn");
    if (resetBtn && phaseIndicator.resetKey) {
      resetBtn.addEventListener("click", () => {
        localStorage.setItem(phaseIndicator.resetKey, "true");
        setIndicator(
          "phases",
          "green",
          "Reiniciado",
          "Indicador reiniciado para este proyecto"
        );
      });
    }

    renderCharts(weekly, activeTotalHours);
    renderPhaseChangesTable(phases);
  } catch (err) {
    const noData = $("noDataMessage");
    if (noData) {
      noData.textContent =
        "No se pudieron cargar los datos del proyecto. Inténtalo más tarde.";
      noData.classList.remove("d-none");
    }
  }
}

async function init() {
  const urlParams = new URLSearchParams(window.location.search);
  const projectCodeParam = urlParams.get("code");
  const projectNameParam = urlParams.get("name");
  const totalHoursParam = urlParams.get("totalHours");
  const totalHours = totalHoursParam ? Number(totalHoursParam) : DEFAULT_TOTAL_HOURS;
  const projectNameEl = $("projectName");
  const projectCodeEl = $("projectCode");
  const backLink = $("backToProjects");
  const pathMatch = window.location.pathname.match(/\/projects\/([^/]+)\/indicators/);
  const projectCode =
    projectCodeParam ||
    window.PROJECT_CODE ||
    (pathMatch ? decodeURIComponent(pathMatch[1]) : "") ||
    (projectCodeEl ? projectCodeEl.textContent.trim() : "");
  if (projectCodeEl && projectCode) {
    projectCodeEl.textContent = projectCode;
  }
  if (backLink && projectCode) {
    const params = new URLSearchParams();
    params.set("q", projectCode);
    const targetUrl = `/estado-proyecto?${params.toString()}`;
    backLink.href = targetUrl;
    backLink.addEventListener("click", (event) => {
      event.preventDefault();
      window.location.href = targetUrl;
    });
  }
  if (!projectCode) return;

  let projectName = projectNameParam;
  if (!projectName) {
    try {
      const details = await fetchJson(
        `/projects/${encodeURIComponent(projectCode)}/details`
      );
      projectName = details?.project?.project_name;
    } catch (err) {
      projectName = "";
    }
  }
  if (projectNameEl && projectName) {
    projectNameEl.textContent = ` · ${projectName}`;
  }

  activeProjectCode = projectCode;
  activeTotalHours = totalHours;
  await loadIndicators();
}

document.addEventListener("DOMContentLoaded", init);
window.addEventListener("focus", () => {
  if (activeProjectCode) {
    loadIndicators();
  }
});
