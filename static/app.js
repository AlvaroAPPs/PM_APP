const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

function isEmpty(v) {
  return v === null || v === undefined || v === "" || v === "NaT";
}
function fmtText(v) {
  return isEmpty(v) ? "—" : String(v);
}
function fmtNum(v) {
  if (isEmpty(v)) return "—";
  const n = Number(v);
  return Number.isFinite(n)
    ? n.toLocaleString("es-ES", { maximumFractionDigits: 2 })
    : String(v);
}
function fmtEur(v) {
  if (isEmpty(v)) return "—";
  const n = Number(v);
  return Number.isFinite(n)
    ? n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })
    : String(v);
}
function fmtPct(v, mode = "0_100") {
  if (isEmpty(v)) return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  const val = mode === "0_1" ? n * 100 : n;
  return `${val.toFixed(2)} %`;
}
function fmtDateISO(v) {
  if (isEmpty(v)) return "—";
  const d = new Date(v + "T00:00:00");
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString("es-ES");
}
function fmtDateTime(v) {
  if (isEmpty(v)) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString("es-ES");
}

function show(id) {
  const el = $(id);
  if (el) el.classList.remove("d-none");
}
function hide(id) {
  const el = $(id);
  if (el) el.classList.add("d-none");
}
function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setKpiColor(id, sign) {
  const el = $(id);
  if (!el) return;
  el.classList.remove("text-danger", "text-success");
  if (sign > 0) el.classList.add("text-danger");
  else if (sign < 0) el.classList.add("text-success");
}

function setActionsEnabled(isEnabled) {
  const actCharts = $("actCharts");
  const actReport = $("actReport");
  if (actCharts) actCharts.disabled = !isEnabled;
  if (actReport) actReport.disabled = !isEnabled;
}

function resetUI() {
  // ocultar secciones
  ["projectHeader", "datesRow", "kpis", "detailsWrap"].forEach(hide);

  // desactivar acciones dependientes de proyecto
  setActionsEnabled(false);

  // limpiar valores visibles
  const idsToClear = [
    "ph_name",
    "ph_code",
    "ph_team",
    "ph_pm",
    "ph_consultant",
    "ph_company_client",
    "ph_snapshot",
    "ph_snapshot_at",
    "date_kickoff",
    "date_design",
    "date_validation",
    "date_golive",
    "date_reception",
    "date_end",

    // KPIs nuevos (fila)
    "kpi_avance_w",
    "kpi_horas_proyecto",
    "kpi_horas_teoricas",
    "kpi_horas_reales",
    "kpi_desviacion_pct",

    // otros KPIs que pudieras mantener
    "kpi_deviation_cd",
    "kpi_payment_pending",
  ];
  idsToClear.forEach((id) => setText(id, "—"));
  setKpiColor("kpi_desviacion_pct", 0);

  const details = $("details");
  if (details) details.innerHTML = "";
}

async function loadProject(code) {
  const res = await fetch(`${API}/projects/${encodeURIComponent(code)}/state`);
  if (!res.ok) {
    resetUI();
    alert(`No puedo cargar el proyecto ${code} (HTTP ${res.status})`);
    return;
  }

  const s = await res.json();
  const l = s.latest;

  if (!s || !s.project || !l) {
    resetUI();
    alert("Respuesta vacía o incompleta del servidor.");
    return;
  }

  // Header (cabecera)
  show("projectHeader");
  setText("ph_name", fmtText(s.project.project_name));
  setText("ph_code", fmtText(s.project.project_code));
  setText("ph_team", fmtText(s.project.team));
  setText("ph_pm", fmtText(s.project.project_manager));
  setText("ph_consultant", fmtText(s.project.consultant));

  const company = fmtText(s.project.company);
  const client = fmtText(s.project.client);
  const cc = [company, client].filter((x) => x !== "—").join(" / ");
  setText("ph_company_client", cc || "—");

  setText(
    "ph_snapshot",
    `${l.snapshot_year}-W${String(l.snapshot_week).padStart(2, "0")}`
  );
  setText("ph_snapshot_at", fmtDateTime(l.snapshot_at));

  // Dates row
  show("datesRow");
  setText("date_kickoff", fmtDateISO(l.date_kickoff));
  setText("date_design", fmtDateISO(l.date_design));
  setText("date_validation", fmtDateISO(l.date_validation));
  setText("date_golive", fmtDateISO(l.date_golive));
  setText("date_reception", fmtDateISO(l.date_reception));
  setText("date_end", fmtDateISO(l.date_end));

  // KPIs
  show("kpis");

  // --- KPI row (Avance / Horas / Desviación) ---
  const avanceW = Number(l.progress_w); // 0..100 esperado
  const horasProyecto = !isEmpty(l.ordered_total)
    ? Number(l.ordered_total)
    : Number(l.ordered_n || 0) + Number(l.ordered_e || 0);

  const horasTeoricas = !isEmpty(l.horas_teoricas)
    ? Number(l.horas_teoricas)
    : Number.isFinite(horasProyecto) && Number.isFinite(avanceW)
    ? horasProyecto * (avanceW / 100.0)
    : NaN;

  const horasReales = !isEmpty(l.real_hours) ? Number(l.real_hours) : NaN;

  const desviacionPct = !isEmpty(l.desviacion_pct)
    ? Number(l.desviacion_pct)
    : Number.isFinite(horasTeoricas) &&
      horasTeoricas !== 0 &&
      Number.isFinite(horasReales)
    ? ((horasReales - horasTeoricas) / horasTeoricas) * 100.0
    : NaN;

  setText("kpi_avance_w", fmtPct(l.progress_w, "0_100"));
  setText(
    "kpi_horas_proyecto",
    Number.isFinite(horasProyecto) ? fmtNum(horasProyecto) : "—"
  );
  setText(
    "kpi_horas_teoricas",
    Number.isFinite(horasTeoricas) ? fmtNum(horasTeoricas) : "—"
  );
  setText(
    "kpi_horas_reales",
    Number.isFinite(horasReales) ? fmtNum(horasReales) : "—"
  );

  if (Number.isFinite(desviacionPct)) {
    setText("kpi_desviacion_pct", `${desviacionPct.toFixed(2)} %`);
    // >0 rojo, <0 verde
    setKpiColor("kpi_desviacion_pct", desviacionPct);
  } else {
    setText("kpi_desviacion_pct", "—");
    setKpiColor("kpi_desviacion_pct", 0);
  }

  // activar acciones cuando ya hay proyecto cargado
  setActionsEnabled(true);

  // Details
  show("detailsWrap");
  const details = $("details");
  if (details) {
    details.innerHTML = "";

    const rows = [
      ["Avance semanal (W)", fmtPct(l.progress_w, "0_100")],
      ["Horas proyecto (Ordered total)", Number.isFinite(horasProyecto) ? fmtNum(horasProyecto) : "—"],
      ["Horas teóricas", Number.isFinite(horasTeoricas) ? fmtNum(horasTeoricas) : "—"],
      ["Horas reales", Number.isFinite(horasReales) ? fmtNum(horasReales) : "—"],
      ["Desviación %", Number.isFinite(desviacionPct) ? `${desviacionPct.toFixed(2)} %` : "—"],

      ["Progreso acumulado (C)", fmtPct(l.progress_c, "0_100")],
      ["Progreso PM", fmtPct(l.progress_pm, "0_100")],
      ["Progreso E", fmtPct(l.progress_e, "0_100")],

      ["Desviación TD", fmtNum(l.deviation_td)],
      ["Desviación CD", fmtNum(l.deviation_cd)],
      ["Desviación PMD", fmtNum(l.deviation_pmd)],

      ["Importe total", fmtEur(l.payment_total)],
      ["Pendiente", fmtEur(l.payment_pending)],
      ["Facturado (%)", fmtPct(l.payment_inv, "0_100")],

      ["Distribución C", fmtPct(l.dist_c, "0_1")],
      ["Distribución PM", fmtPct(l.dist_pm, "0_1")],
      ["Distribución E", fmtPct(l.dist_e, "0_1")],

      ["Fase pedido", fmtText(l.order_phase)],
      ["Estado interno", fmtText(l.internal_status)],
      ["Tipo proyecto", fmtText(l.project_type)],
      ["Oferta", fmtText(l.offer_code)],
      ["Fecha reporte", fmtText(l.report_date)],

      ["Replanificación", fmtText(l.replanning_reason)],
      ["Comentarios", fmtText(l.comments)],
    ];

    rows.forEach(([label, value]) => {
      const col = document.createElement("div");
      col.className = "col-12 col-md-6";
      col.innerHTML = `
        <div class="d-flex justify-content-between align-items-start border rounded-4 p-2 px-3" style="background:#f8fafc;">
          <div class="text-muted small fw-semibold" style="max-width:45%;">${label}</div>
          <div class="fw-bold text-end" style="max-width:55%; white-space:pre-wrap;">${value}</div>
        </div>
      `;
      details.appendChild(col);
    });
  }
}

function onLoadClick() {
  const input = $("q");
  const code = input ? input.value.trim() : "";
  if (!code) {
    resetUI();
    alert("Introduce un código de proyecto.");
    return;
  }
  loadProject(code);
}

document.addEventListener("DOMContentLoaded", () => {
  resetUI(); // todo en blanco al entrar

  // Buscar
  const btn = $("btnLoad");
  if (btn) btn.addEventListener("click", onLoadClick);

  const input = $("q");
  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") onLoadClick();
    });
  }

  // Sidebar actions (no rompe si no existen)
  const actNewData = $("actNewData");
  if (actNewData) {
    actNewData.addEventListener("click", () => {
      window.location.href = "/importacion";
    });
  }

  const actCharts = $("actCharts");
  if (actCharts) {
    actCharts.addEventListener("click", () => {
      alert("Pendiente: Gráficas proyecto (siguiente paso).");
    });
  }

  const actReport = $("actReport");
  if (actReport) {
    actReport.addEventListener("click", () => {
      alert("Pendiente: Generar informe (siguiente paso).");
    });
  }
});
