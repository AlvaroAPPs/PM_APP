const $ = (id) => document.getElementById(id);

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

  const changesByPhase = {};
  PHASES.forEach((phase) => {
    changesByPhase[phase.key] = [];
  });

  for (let i = 1; i < phasesHistory.length; i += 1) {
    const prev = phasesHistory[i - 1];
    const curr = phasesHistory[i];
    const snapshotLabel = formatWeekLabel(curr.year, curr.week);
    PHASES.forEach((phase) => {
      const prevDate = prev[phase.key] || null;
      const currDate = curr[phase.key] || null;
      if (prevDate !== currDate) {
        changesByPhase[phase.key].push({
          snapshot: snapshotLabel,
          oldDate: prevDate,
          newDate: currDate,
        });
      }
    });
  }

  PHASES.forEach((phase) => {
    const changes = changesByPhase[phase.key];
    const lastChanges = changes.slice(-5).reverse();
    const changesHtml =
      lastChanges.length === 0
        ? "<div class=\"muted\">Sin cambios</div>"
        : lastChanges
            .map(
              (change) =>
                `<div><span class="mono">${change.snapshot}</span> · ${formatDate(
                  change.oldDate
                )} → ${formatDate(change.newDate)}</div>`
            )
            .join("");
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="fw-semibold">${phase.label}</td>
      <td>${changesHtml}</td>
      <td>${changes.length}</td>
    `;
    tbody.appendChild(row);
  });
}

function buildLineChart(ctx, labels, datasetLabel, data, color) {
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
      },
      scales: {
        y: {
          ticks: { callback: (value) => value.toString() },
        },
      },
    },
  });
}

function buildBarChart(ctx, labels, datasets) {
  return new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true },
      },
    },
  });
}

function buildSCurveChart(ctx, labels, actualData, projectedData) {
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Real",
          data: actualData,
          borderColor: "#2563eb",
          backgroundColor: "#2563eb",
          tension: 0.25,
        },
        {
          label: "Proyección",
          data: projectedData,
          borderColor: "#f97316",
          backgroundColor: "#f97316",
          borderDash: [6, 6],
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true },
      },
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
        },
      },
    },
  });
}

function buildProjection(weekly, labels, cumulativeActual) {
  if (!weekly.length) {
    return { labels, actual: cumulativeActual, projected: [] };
  }

  const recent = weekly.slice(-4);
  const productivityRates = recent
    .map((item) => {
      const progress = toNumber(item.progress_w);
      const hours = toNumber(item.real_hours);
      if (progress === null || hours === null || hours <= 0) return null;
      return progress / hours;
    })
    .filter((value) => value !== null);

  const fallbackRates = recent
    .map((item) => {
      const progress = toNumber(item.progress_w);
      const hours = toNumber(item.horas_teoricas);
      if (progress === null || hours === null || hours <= 0) return null;
      return progress / hours;
    })
    .filter((value) => value !== null);

  const capacityReal = recent
    .map((item) => toNumber(item.real_hours))
    .filter((value) => value !== null && value > 0);
  const capacityTheoretical = recent
    .map((item) => toNumber(item.horas_teoricas))
    .filter((value) => value !== null && value > 0);

  const productivityRate = average(productivityRates) ?? average(fallbackRates);
  const weeklyCapacity = average(capacityReal) ?? average(capacityTheoretical);

  if (!productivityRate || !weeklyCapacity) {
    return { labels, actual: cumulativeActual, projected: [] };
  }

  const projectedLabels = [...labels];
  const projectedData = new Array(labels.length).fill(null);
  const actualData = [...cumulativeActual];

  let projectedProgress = cumulativeActual[cumulativeActual.length - 1] ?? 0;
  let remaining = 100 - projectedProgress;
  let currentYear = weekly[weekly.length - 1].year;
  let currentWeek = weekly[weekly.length - 1].week;

  let guard = 0;
  while (remaining > 0 && guard < 60) {
    guard += 1;
    [currentYear, currentWeek] = addWeek(currentYear, currentWeek);
    const weeklyProgress = weeklyCapacity * productivityRate;
    projectedProgress = Math.min(100, projectedProgress + weeklyProgress);
    remaining = 100 - projectedProgress;
    projectedLabels.push(formatWeekLabel(currentYear, currentWeek));
    projectedData.push(projectedProgress);
    actualData.push(null);
    if (projectedProgress >= 100) break;
  }

  return { labels: projectedLabels, actual: actualData, projected: projectedData };
}

function renderCharts(weekly) {
  const labels = weekly.map((item) => formatWeekLabel(item.year, item.week));
  const progressData = weekly.map((item) => toNumber(item.progress_w));
  const deviationData = weekly.map((item) => toNumber(item.desviacion_pct));
  const realHoursData = weekly.map((item) => toNumber(item.real_hours));
  const theoreticalHoursData = weekly.map((item) => toNumber(item.horas_teoricas));

  buildLineChart(
    $("chartProgress"),
    labels,
    "Progreso semanal",
    progressData,
    "#2563eb"
  );
  buildLineChart(
    $("chartDeviation"),
    labels,
    "Desviación %",
    deviationData,
    "#dc2626"
  );
  buildLineChart(
    $("chartRealHours"),
    labels,
    "Horas reales",
    realHoursData,
    "#0ea5e9"
  );

  buildBarChart($("chartHoursCompare"), labels, [
    {
      label: "Horas reales",
      data: realHoursData,
      backgroundColor: "#1d4ed8",
    },
    {
      label: "Horas teóricas",
      data: theoreticalHoursData,
      backgroundColor: "#93c5fd",
    },
  ]);

  const cumulativeActual = [];
  let cumulative = 0;
  weekly.forEach((item) => {
    const progress = toNumber(item.progress_w);
    if (progress !== null) {
      cumulative = Math.min(100, cumulative + progress);
    }
    cumulativeActual.push(cumulative);
  });

  const projection = buildProjection(weekly, labels, cumulativeActual);
  buildSCurveChart(
    $("chartSCurve"),
    projection.labels,
    projection.actual,
    projection.projected
  );
}

async function init() {
  const projectCode = window.PROJECT_CODE;
  if (!projectCode) return;

  try {
    const [weekly, phases] = await Promise.all([
      fetchJson(`/projects/${encodeURIComponent(projectCode)}/metrics/weekly`),
      fetchJson(`/projects/${encodeURIComponent(projectCode)}/metrics/phases`),
    ]);

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

    renderCharts(weekly);
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
