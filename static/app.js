const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);
let currentProjectId = null;
let currentProjectCode = null;
let currentProjectName = null;
let currentProjectTotalHours = null;

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
function fmtFixed2(v) {
  if (isEmpty(v)) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : String(v);
}
function fmtDateISO(v) {
  if (isEmpty(v)) return "—";
  if (v instanceof Date) {
    return Number.isNaN(v.getTime()) ? "—" : v.toLocaleDateString("es-ES");
  }
  if (typeof v === "number") {
    const numeric = new Date(v);
    return Number.isNaN(numeric.getTime())
      ? "—"
      : numeric.toLocaleDateString("es-ES");
  }
  const direct = new Date(v);
  if (!Number.isNaN(direct.getTime())) {
    return direct.toLocaleDateString("es-ES");
  }
  const d = new Date(`${v}T00:00:00`);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString("es-ES");
}
function fmtDateTime(v) {
  if (isEmpty(v)) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString("es-ES");
}
function toInputValue(v) {
  if (isEmpty(v)) return "0";
  const n = Number(v);
  return Number.isFinite(n) ? String(n) : "0";
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
function setValue(id, value) {
  const el = $(id);
  if (el) el.value = value;
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
  currentProjectId = null;
  currentProjectCode = null;
  currentProjectName = null;
  currentProjectTotalHours = null;
  // ocultar secciones
  ["projectHeader", "datesRow", "kpis", "excelCommentsCard", "detailsSection"].forEach(hide);

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
    "kpi_avance_w",
    "kpi_horas_proyecto",
    "kpi_horas_teoricas",
    "kpi_horas_reales",
    "kpi_desviacion_pct",
    "excel_comments",
    "weekly_progress_delta",
    "weekly_real_hours_delta",
    "weekly_theoretical_hours_delta",
    "weekly_deviation_pct_delta",
    "weekly_productivity",
    "economic_total",
    "economic_pending",
    "economic_paid_pct",
  ];
  idsToClear.forEach((id) => setText(id, "—"));
  setKpiColor("kpi_desviacion_pct", 0);
  setValue("phase_design", "");
  setValue("phase_development", "");
  setValue("phase_pem", "");
  setValue("phase_hypercare", "");
  setValue("role_pm", "");
  setValue("role_consultant", "");
  setValue("role_technician", "");
  setValue("project_comment_input", "");
}

async function loadProject(code) {
  const res = await fetch(`${API}/projects/${encodeURIComponent(code)}/details`);
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
  currentProjectId = s.project.id;
  currentProjectCode = s.project.project_code;
  currentProjectName = s.project.project_name;

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

  // activar acciones cuando ya hay proyecto cargado
  setActionsEnabled(true);

  // KPIs
  show("kpis");

  // --- KPI row (Avance / Horas / Desviación) ---
  const avanceW = Number(l.progress_w); // 0..100 esperado
  const horasProyecto = !isEmpty(l.ordered_total)
    ? Number(l.ordered_total)
    : Number(l.ordered_n || 0) + Number(l.ordered_e || 0);
  currentProjectTotalHours = Number.isFinite(horasProyecto) ? horasProyecto : null;

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

  show("excelCommentsCard");
  const excelComments = s.excel_comments ?? l.comments;
  setText("excel_comments", fmtText(excelComments));

  show("detailsSection");
  setText("weekly_progress_delta", fmtPct(l.progress_w_delta, "0_100"));
  setText("weekly_real_hours_delta", fmtNum(l.real_hours_delta));
  setText("weekly_theoretical_hours_delta", fmtNum(l.horas_teoricas_delta));
  setText("weekly_deviation_pct_delta", fmtPct(l.desviacion_pct_delta, "0_100"));
  setText("weekly_productivity", fmtFixed2(l.productividad_proyecto));

  setText("economic_total", fmtEur(l.payment_total));
  setText("economic_pending", fmtEur(l.payment_pending));
  setText("economic_paid_pct", fmtPct(l.payment_inv, "0_100"));

  const phaseValues = s.assigned_hours_phase || {};
  setValue("phase_design", toInputValue(phaseValues.design ?? 0));
  setValue("phase_development", toInputValue(phaseValues.development ?? 0));
  setValue("phase_pem", toInputValue(phaseValues.pem ?? 0));
  setValue("phase_hypercare", toInputValue(phaseValues.hypercare ?? 0));

  const roleValues = s.assigned_hours_role || {};
  setValue("role_pm", toInputValue(roleValues.pm ?? 0));
  setValue("role_consultant", toInputValue(roleValues.consultant ?? 0));
  setValue("role_technician", toInputValue(roleValues.technician ?? 0));

  setValue("project_comment_input", s.project_comment ?? "");
}

async function postJson(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || `HTTP ${res.status}`);
  }
  return res.json();
}

async function savePhaseHours() {
  if (!currentProjectId) {
    alert("Carga un proyecto antes de guardar.");
    return;
  }
  const status = $("phaseStatus");
  if (status) status.textContent = "Guardando...";
  try {
    await Promise.all([
      postJson(`${API}/projects/${currentProjectId}/assigned-hours/phase`, {
        phase: "design",
        hours: Number($("phase_design").value || 0),
      }),
      postJson(`${API}/projects/${currentProjectId}/assigned-hours/phase`, {
        phase: "development",
        hours: Number($("phase_development").value || 0),
      }),
      postJson(`${API}/projects/${currentProjectId}/assigned-hours/phase`, {
        phase: "pem",
        hours: Number($("phase_pem").value || 0),
      }),
      postJson(`${API}/projects/${currentProjectId}/assigned-hours/phase`, {
        phase: "hypercare",
        hours: Number($("phase_hypercare").value || 0),
      }),
    ]);
    if (status) status.textContent = "Guardado";
  } catch (err) {
    if (status) status.textContent = "Error al guardar";
    alert(err.message);
  }
}

async function saveRoleHours() {
  if (!currentProjectId) {
    alert("Carga un proyecto antes de guardar.");
    return;
  }
  const status = $("roleStatus");
  if (status) status.textContent = "Guardando...";
  try {
    await Promise.all([
      postJson(`${API}/projects/${currentProjectId}/assigned-hours/role`, {
        role: "pm",
        hours: Number($("role_pm").value || 0),
      }),
      postJson(`${API}/projects/${currentProjectId}/assigned-hours/role`, {
        role: "consultant",
        hours: Number($("role_consultant").value || 0),
      }),
      postJson(`${API}/projects/${currentProjectId}/assigned-hours/role`, {
        role: "technician",
        hours: Number($("role_technician").value || 0),
      }),
    ]);
    if (status) status.textContent = "Guardado";
  } catch (err) {
    if (status) status.textContent = "Error al guardar";
    alert(err.message);
  }
}

async function saveProjectComment() {
  if (!currentProjectId) {
    alert("Carga un proyecto antes de guardar.");
    return;
  }
  const status = $("commentStatus");
  if (status) status.textContent = "Guardando...";
  try {
    await postJson(`${API}/projects/${currentProjectId}/comments`, {
      comment_text: $("project_comment_input").value || "",
    });
    if (status) status.textContent = "Guardado";
  } catch (err) {
    if (status) status.textContent = "Error al guardar";
    alert(err.message);
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
  currentProjectId = null;

  // Buscar
  const btn = $("btnLoad");
  if (btn) btn.addEventListener("click", onLoadClick);

  const input = $("q");
  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") onLoadClick();
    });
  }

  const urlParams = new URLSearchParams(window.location.search);
  const prefill = urlParams.get("q");
  if (prefill && input) {
    input.value = prefill;
    loadProject(prefill);
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
      if (!currentProjectCode) {
        alert("Carga un proyecto antes de continuar.");
        return;
      }
      const params = new URLSearchParams();
      params.set("code", currentProjectCode);
      if (currentProjectName) params.set("name", currentProjectName);
      if (Number.isFinite(currentProjectTotalHours)) {
        params.set("totalHours", String(currentProjectTotalHours));
      }
      window.location.href = `/projects/${encodeURIComponent(currentProjectCode)}/indicators?${params.toString()}`;
    });
  }

  const actReport = $("actReport");
  if (actReport) {
    actReport.addEventListener("click", () => {
      alert("Pendiente: Generar informe (siguiente paso).");
    });
  }

  const savePhase = $("savePhase");
  if (savePhase) savePhase.addEventListener("click", savePhaseHours);

  const saveRole = $("saveRole");
  if (saveRole) saveRole.addEventListener("click", saveRoleHours);

  const saveComment = $("saveProjectComment");
  if (saveComment) saveComment.addEventListener("click", saveProjectComment);
});
