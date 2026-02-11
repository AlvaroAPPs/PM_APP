const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

let viewMode = "month";
let anchorDate = new Date();
let selectedDate = new Date();
let weekTasks = [];
let selectedTask = null;
let detailModal = null;
let editModal = null;

function toIsoDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseIsoDate(value) {
  if (!value) return null;
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmtDate(value) {
  const d = value instanceof Date ? value : parseIsoDate(value);
  if (!d) return "—";
  return d.toLocaleDateString("es-ES");
}

function statusLabel(status) {
  return { OPEN: "Abierta", IN_PROGRESS: "Proceso", PAUSED: "Parada", CLOSED: "Cerrada" }[status] || status;
}

function typeLabel(type) {
  return type === "PP" ? "PP" : "Tarea";
}

function startOfWeek(date) {
  const d = new Date(date);
  const day = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - day);
  d.setHours(0, 0, 0, 0);
  return d;
}

function endOfWeek(date) {
  const d = startOfWeek(date);
  d.setDate(d.getDate() + 6);
  return d;
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

async function fetchWeekTasks() {
  const start = startOfWeek(selectedDate);
  const end = endOfWeek(selectedDate);
  const params = new URLSearchParams();
  params.set("start_date", toIsoDate(start));
  params.set("end_date", toIsoDate(end));
  params.set("include_closed", "false");

  const res = await fetch(`${API}/project-tasks?${params.toString()}`);
  weekTasks = res.ok ? await res.json() : [];
  renderWeekTasks();
  renderCalendar();
}

function renderWeekTasks() {
  const container = $("weekTasks");
  if (!container) return;
  container.innerHTML = "";

  const start = startOfWeek(selectedDate);
  const end = endOfWeek(selectedDate);
  $("weekLabel").textContent = `${fmtDate(start)} - ${fmtDate(end)}`;

  if (!weekTasks.length) {
    container.innerHTML = '<div class="muted small">No hay tareas planificadas esta semana.</div>';
    return;
  }

  for (const task of weekTasks) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "list-group-item list-group-item-action";
    btn.innerHTML = `
      <div class="d-flex justify-content-between gap-2">
        <div>
          <div class="fw-semibold">${task.title || "(Sin título)"}</div>
          <div class="small muted">${task.project_code || "—"} · ${task.project_name || "—"}</div>
        </div>
        <div class="text-end">
          <div class="small">${fmtDate(task.planned_date)}</div>
          <span class="badge text-bg-light border">${statusLabel(task.status)}</span>
        </div>
      </div>
    `;
    btn.addEventListener("click", () => openTaskDetail(task));
    container.appendChild(btn);
  }
}

function renderCalendar() {
  const grid = $("calendarGrid");
  if (!grid) return;
  grid.innerHTML = "";

  const weekStart = startOfWeek(selectedDate);
  const weekEnd = endOfWeek(selectedDate);
  $("calendarRangeLabel").textContent = viewMode === "month"
    ? anchorDate.toLocaleDateString("es-ES", { month: "long", year: "numeric" })
    : `${fmtDate(weekStart)} - ${fmtDate(weekEnd)}`;

  const tasksByDay = new Map();
  for (const task of weekTasks) {
    if (!task.planned_date) continue;
    const key = task.planned_date;
    if (!tasksByDay.has(key)) tasksByDay.set(key, []);
    tasksByDay.get(key).push(task);
  }

  if (viewMode === "week") {
    const start = startOfWeek(anchorDate);
    for (let i = 0; i < 7; i += 1) {
      const day = new Date(start);
      day.setDate(start.getDate() + i);
      grid.appendChild(buildDayCell(day, tasksByDay, false));
    }
    return;
  }

  const first = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1);
  const start = startOfWeek(first);
  for (let i = 0; i < 42; i += 1) {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    const outside = day.getMonth() !== anchorDate.getMonth();
    grid.appendChild(buildDayCell(day, tasksByDay, outside));
  }
}

function buildDayCell(day, tasksByDay, outsideMonth) {
  const cell = document.createElement("button");
  cell.type = "button";
  cell.className = "calendar-cell text-start";
  if (sameDay(day, selectedDate)) cell.classList.add("active");
  if (outsideMonth) cell.classList.add("opacity-50");

  const key = toIsoDate(day);
  const count = (tasksByDay.get(key) || []).length;
  cell.innerHTML = `<div class="num">${day.getDate()}</div>${count ? `<span class="task-chip">${count} tareas</span>` : ""}`;
  cell.addEventListener("click", () => {
    selectedDate = new Date(day);
    fetchWeekTasks();
  });
  return cell;
}

function openTaskDetail(task) {
  selectedTask = task;
  $("detailProject").textContent = `${task.project_code || "—"} - ${task.project_name || "—"}`;
  $("detailTitle").textContent = task.title || "—";
  $("detailType").textContent = typeLabel(task.type);
  $("detailStatus").textContent = statusLabel(task.status);
  $("detailOwner").textContent = task.owner_role || "—";
  $("detailDate").textContent = fmtDate(task.planned_date);
  $("detailDescription").textContent = task.description || "—";
  detailModal.show();
}

function openEditModal() {
  if (!selectedTask) return;
  $("editTitle").value = selectedTask.title || "";
  $("editType").value = selectedTask.type || "TASK";
  $("editOwner").value = selectedTask.owner_role || "PM";
  $("editDate").value = selectedTask.planned_date || "";
  $("editStatus").value = selectedTask.status || "OPEN";
  $("editDescription").value = selectedTask.description || "";
  $("editError").textContent = "";
  editModal.show();
}

async function saveEdit() {
  if (!selectedTask) return;
  const payload = {
    title: ($("editTitle").value || "").trim(),
    type: $("editType").value,
    owner_role: $("editOwner").value,
    planned_date: $("editDate").value || null,
    status: $("editStatus").value,
    description: ($("editDescription").value || "").trim(),
  };
  if (!payload.title || !payload.description) {
    $("editError").textContent = "Título y descripción son obligatorios.";
    return;
  }

  const res = await fetch(`${API}/project-tasks/${selectedTask.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    $("editError").textContent = "No se pudo actualizar la tarea.";
    return;
  }

  editModal.hide();
  detailModal.hide();
  await fetchWeekTasks();
}

async function closeTask() {
  if (!selectedTask) return;
  const res = await fetch(`${API}/project-tasks/${selectedTask.id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "CLOSED" }),
  });
  if (!res.ok) return;
  detailModal.hide();
  await fetchWeekTasks();
}

function navigateTask() {
  if (!selectedTask) return;
  const params = new URLSearchParams();
  params.set("project_id", String(selectedTask.project_id));
  params.set("project_code", selectedTask.project_code || "");
  window.location.href = `/tasks?${params.toString()}`;
}

function goProject() {
  if (!selectedTask) return;
  const params = new URLSearchParams();
  params.set("q", selectedTask.project_code || "");
  params.set("return_to", window.location.pathname);
  window.location.href = `/estado-proyecto?${params.toString()}`;
}

function moveRange(step) {
  if (viewMode === "month") {
    anchorDate = new Date(anchorDate.getFullYear(), anchorDate.getMonth() + step, 1);
    if (selectedDate.getMonth() !== anchorDate.getMonth() || selectedDate.getFullYear() !== anchorDate.getFullYear()) {
      selectedDate = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1);
    }
  } else {
    anchorDate = new Date(anchorDate);
    anchorDate.setDate(anchorDate.getDate() + (7 * step));
    selectedDate = new Date(anchorDate);
  }
  fetchWeekTasks();
}

function setView(mode) {
  viewMode = mode;
  $("viewMonth").className = mode === "month" ? "btn btn-dark" : "btn btn-outline-dark";
  $("viewWeek").className = mode === "week" ? "btn btn-dark" : "btn btn-outline-dark";
  renderCalendar();
}

document.addEventListener("DOMContentLoaded", async () => {
  detailModal = new bootstrap.Modal($("taskDetailModal"));
  editModal = new bootstrap.Modal($("taskEditModal"));

  $("viewMonth")?.addEventListener("click", () => setView("month"));
  $("viewWeek")?.addEventListener("click", () => setView("week"));
  $("prevRange")?.addEventListener("click", () => moveRange(-1));
  $("nextRange")?.addEventListener("click", () => moveRange(1));
  $("todayRange")?.addEventListener("click", () => {
    anchorDate = new Date();
    selectedDate = new Date();
    fetchWeekTasks();
  });

  $("detailEdit")?.addEventListener("click", openEditModal);
  $("saveEditTask")?.addEventListener("click", saveEdit);
  $("detailClose")?.addEventListener("click", closeTask);
  $("detailNavigate")?.addEventListener("click", navigateTask);
  $("detailProjectBtn")?.addEventListener("click", goProject);

  await fetchWeekTasks();
  renderCalendar();
});
