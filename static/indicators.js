const $ = (id) => document.getElementById(id);

const MAX_CHART_POINTS = 25;
const DEFAULT_TOTAL_HOURS = null;
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
    return { status: "orange", label: "N/A", detail: "Sin semana anterior" };
  }
  const latest = weekly[weekly.length - 1];
  const prev = weekly[weekly.length - 2];

  const latestReal = toNumber(latest.real_hours);
  const prevReal = toNumber(prev.real_hours);
  const latestProgress = toNumber(latest.progress_w);
  const prevProgress = toNumber(prev.progress_w);
  const latestTheoretical = toNumber(latest.horas_teoricas);
  const prevTheoretical = toNumber(prev.horas_teoricas);

  if (
    latestReal === null ||
    prevReal === null ||
    latestProgress === null ||
    prevProgress === null
  ) {
    return { status: "orange", label: "N/A", detail: "Datos insuficientes" };
  }

  if (latestReal > prevReal && latestProgress <= prevProgress) {
    return {
      status: "red",
      label: "Alerta",
      detail: "Suben horas reales sin mejorar el progreso",
    };
  }

  if (latestTheoretical !== null && latestReal > latestTheoretical) {
    return {
      status: "amber",
      label: "En riesgo",
      detail: "Horas reales por encima de las teóricas",
    };
  }

  if (prevTheoretical !== null && latestReal < prevTheoretical) {
    return {
      status: "green",
      label: "En control",
      detail: "Horas reales por debajo de la teoría previa",
    };
  }

  return { status: "orange", label: "N/A", detail: "Sin condición aplicable" };
}

function computeDeviationIndicator(weekly) {
  if (weekly.length < 2) {
    return { status: "orange", label: "N/A", detail: "Sin semana anterior" };
  }
  const latest = weekly[weekly.length - 1];
  const prev = weekly[weekly.length - 2];

  const latestDev = toNumber(latest.desviacion_pct);
  const prevDev = toNumber(prev.desviacion_pct);
  if (latestDev === null || prevDev === null) {
    return { status: "orange", label: "N/A", detail: "Datos insuficientes" };
  }
  if (latestDev > prevDev) {
    return {
      status: "red",
      label: "Aumenta",
      detail: `Sube de ${formatNumber(prevDev)}% a ${formatNumber(latestDev)}%`,
    };
  }
  if (latestDev === prevDev) {
    return {
      status: "amber",
      label: "Estable",
      detail: `Se mantiene en ${formatNumber(latestDev)}%`,
    };
  }
  return {
    status: "green",
    label: "Mejora",
    detail: `Baja de ${formatNumber(prevDev)}% a ${formatNumber(latestDev)}%`,
  };
}

function computePhaseIndicator(phasesHistory, projectCode) {
  const resetKey = `phaseIndicatorReset:${projectCode}`;
  const resetValue = localStorage.getItem(resetKey);
  if (resetValue === "true") {
    return {
      status: "orange",
      label: "Reiniciado",
      detail: "Indicador reiniciado para este proyecto",
      resetKey,
    };
  }

  const changes = {};
  PHASES.forEach((phase) => {
    changes[phase.key] = { later: false, earlier: false, changed: false };
  });
  for (let i = 1; i < phasesHistory.length; i += 1) {
    const prev = phasesHistory[i - 1];
    const curr = phasesHistory[i];
    PHASES.forEach((phase) => {
      const prevDate = prev[phase.key] || null;
      const currDate = curr[phase.key] || null;
      if (prevDate !== currDate) {
        changes[phase.key].changed = true;
        let direction = "unknown";
        if (prevDate && currDate) {
          const prevTime = new Date(`${prevDate}T00:00:00`).getTime();
          const currTime = new Date(`${currDate}T00:00:00`).getTime();
          if (!Number.isNaN(prevTime) && !Number.isNaN(currTime)) {
            if (currTime > prevTime) direction = "later";
            if (currTime < prevTime) direction = "earlier";
          }
        }
        if (direction === "later") changes[phase.key].later = true;
        if (direction === "earlier") changes[phase.key].earlier = true;
      }
    });
  }

  const firstLater = PHASES.find((phase) => changes[phase.key].later);
  if (firstLater) {
    return {
      status: "red",
      label: "Retraso",
      detail: `Primera fase afectada: ${firstLater.label}`,
      resetKey,
    };
  }
  const firstEarlier = PHASES.find((phase) => changes[phase.key].earlier);
  if (firstEarlier) {
    return {
      status: "green",
      label: "Mejora",
      detail: `Primera fase afectada: ${firstEarlier.label}`,
      resetKey,
    };
  }
  const firstChanged = PHASES.find((phase) => changes[phase.key].changed);
  if (firstChanged) {
    return {
      status: "orange",
      label: "Cambio sin dirección",
      detail: `Primera fase afectada: ${firstChanged.label}`,
      resetKey,
    };
  }
  return {
    status: "orange",
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
      <td colspan="4" class="muted">Sin historial suficiente</td>
    `;
    tbody.appendChild(row);
    return;
  }

  const prev = phasesHistory[phasesHistory.length - 2];
  const curr = phasesHistory[phasesHistory.length - 1];

  PHASES.forEach((phase) => {
    const prevDate = prev[phase.key] || null;
    const currDate = curr[phase.key] || null;
    const changed =
      (prevDate || currDate) && prevDate !== currDate ? 1 : 0;
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="fw-semibold">${phase.label}</td>
      <td>${formatDate(prevDate)}</td>
      <td>${formatDate(currDate)}</td>
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

function buildSCurveChart(ctx, actualPoints, projectedPoints) {
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
          label: "Proyección",
          data: projectedPoints,
          borderColor: "#f97316",
          backgroundColor: "#f97316",
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

function buildProjectionForHours(progressCumulative, realCumulative, weekLabels) {
  if (!progressCumulative.length || !realCumulative.length) {
    return {
      actualPoints: [],
      projectedPoints: [],
      projectedHoursAtClose: null,
      finishingWeekLabel: "N/A",
    };
  }

  const latestProgress = progressCumulative[progressCumulative.length - 1];
  const latestReal = realCumulative[realCumulative.length - 1];

  if (!Number.isFinite(latestProgress) || latestProgress <= 0 || !Number.isFinite(latestReal)) {
    return {
      actualPoints: [],
      projectedPoints: [],
      projectedHoursAtClose: null,
      finishingWeekLabel: "N/A",
    };
  }

  const projectedHoursAtClose = latestReal / (latestProgress / 100);

  const actualPoints = progressCumulative
    .map((value, index) => ({
      x: value,
      y: realCumulative[index],
    }))
    .filter(
      (point) => Number.isFinite(point.x) && Number.isFinite(point.y)
    );

  const projectedPoints = [
    { x: latestProgress, y: latestReal },
    { x: 100, y: projectedHoursAtClose },
  ];

  const progressDeltas = toDeltaSeries(progressCumulative);
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
    projectedPoints,
    projectedHoursAtClose,
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
  const hoursCompareDomain = calculateDomain(
    realWeeklyHours.concat(theoreticalWeeklyHours)
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
    labels,
    [
      {
        label: "Horas reales",
        data: realWeeklyHours.map((value) =>
          value === null ? null : Math.round(value)
        ),
        backgroundColor: "#1d4ed8",
      },
      {
        label: "Horas teóricas",
        data: theoreticalWeeklyHours,
        backgroundColor: "#93c5fd",
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
  const weekOrder = visibleWeekly.map((item) => [item.year, item.week]);
  const projection = buildProjectionForHours(
    progressCumulative,
    realCumulative,
    weekOrder
  );
  buildSCurveChart(
    $("chartSCurve"),
    projection.actualPoints,
    projection.projectedPoints
  );

  const projectionHours = $("projectionHours");
  if (projectionHours) {
    projectionHours.textContent =
      projection.projectedHoursAtClose !== null
        ? `${formatInt(projection.projectedHoursAtClose)} h`
        : "N/A";
  }
  const projectionWeek = $("projectionWeek");
  if (projectionWeek) {
    projectionWeek.textContent = projection.finishingWeekLabel;
  }
}

async function init() {
  const urlParams = new URLSearchParams(window.location.search);
  const projectCode = urlParams.get("code") || window.PROJECT_CODE;
  const projectName = urlParams.get("name");
  const totalHoursParam = urlParams.get("totalHours");
  const totalHours = totalHoursParam ? Number(totalHoursParam) : DEFAULT_TOTAL_HOURS;
  const projectNameEl = $("projectName");
  const projectCodeEl = $("projectCode");
  const backLink = $("backToProjects");
  if (projectCodeEl && projectCode) {
    projectCodeEl.textContent = projectCode;
  }
  if (projectNameEl) {
    projectNameEl.textContent = projectName ? ` · ${projectName}` : "";
  }
  if (backLink && projectCode) {
    const params = new URLSearchParams();
    params.set("q", projectCode);
    backLink.href = `/estado-proyecto?${params.toString()}`;
  }
  if (!projectCode) return;

  try {
    const [weeklyRaw, phasesRaw] = await Promise.all([
      fetchJson(`/projects/${encodeURIComponent(projectCode)}/metrics/weekly`),
      fetchJson(`/projects/${encodeURIComponent(projectCode)}/metrics/phases`),
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

    const phaseIndicator = computePhaseIndicator(phases, projectCode);
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
          "orange",
          "Reiniciado",
          "Indicador reiniciado para este proyecto"
        );
      });
    }

    renderCharts(weekly, totalHours);
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

document.addEventListener("DOMContentLoaded", init);
