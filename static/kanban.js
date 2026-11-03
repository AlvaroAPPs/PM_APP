const API = "";
const $ = (id) => document.getElementById(id);

const SUBTASKS_MARKER = "\n\n---SUBTASKS---\n";
const FILTERS_KEY = "kanban.filters.v1";
const COLUMNS = [
  { key: "TODO", label: "Por hacer" },
  { key: "TODAY", label: "HOY" },
  { key: "IN_PROGRESS", label: "En curso" },
  { key: "WAITING", label: "Esperando" },
  { key: "DONE", label: "Hecho" },
];
const COLUMN_STATUS = { TODO: "OPEN", TODAY: "OPEN", IN_PROGRESS: "IN_PROGRESS", WAITING: "PAUSED", DONE: "CLOSED" };
const OWNER_LABELS = { PM: "PM", CONSULTORIA: "Consultoría", TECH: "Tech", COMERCIAL: "Comercial", CLIENTE: "Cliente" };

let tasks = [];
let filters = loadFilters();
let selectedTask = null;
let editModal = null;
let rescheduleModal = null;
let rescheduleResolve = null;
let draggedTaskId = null;

function isoDate(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function todayIso() {
  return isoDate(new Date());
}

function addDaysIso(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return isoDate(d);
}

function nextMondayIso() {
  const d = new Date();
  const offset = ((8 - d.getDay()) % 7) || 7;
  d.setDate(d.getDate() + offset);
  return isoDate(d);
}

function weekRangeIso() {
  const d = new Date();
  const monday = new Date(d);
  monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return [isoDate(monday), isoDate(sunday)];
}

function fmtDate(v) {
  if (!v) return "Sin fecha";
  const d = new Date(`${v}T00:00:00`);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit" });
}

function fmtDateTime(v) {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("es-ES");
}

function splitDescriptionAndSubtasks(rawDescription) {
  const text = rawDescription || "";
  const markerIdx = text.indexOf(SUBTASKS_MARKER);
  if (markerIdx < 0) return { description: text, subtasks: [] };
  const tail = text.slice(markerIdx + SUBTASKS_MARKER.length);
  const subtasks = tail
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("[ ] ") || line.startsWith("[x] ") || line.startsWith("[X] "))
    .map((line) => ({ done: line[1].toLowerCase() === "x", text: line.slice(4).trim() }))
    .filter((row) => row.text.length > 0);
  return { description: text.slice(0, markerIdx).trimEnd(), subtasks };
}

function composeDescriptionWithSubtasks(description, subtasks) {
  const cleanDescription = (description || "").trim();
  const cleanSubtasks = (subtasks || []).filter((row) => row.text && row.text.trim());
  if (!cleanSubtasks.length) return cleanDescription;
  const lines = cleanSubtasks.map((row) => `[${row.done ? "x" : " "}] ${row.text.trim()}`);
  return `${cleanDescription}${SUBTASKS_MARKER}${lines.join("\n")}`;
}

function loadFilters() {
  const empty = { search: "", type: "", owner: "", date: "", hiddenProjects: [] };
  try {
    const saved = JSON.parse(localStorage.getItem(FILTERS_KEY) || "null");
    return saved ? { ...empty, ...saved } : empty;
  } catch {
    return empty;
  }
}

function saveFilters() {
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify(filters));
  } catch {
    /* sin almacenamiento: los filtros solo duran esta visita */
  }
}

// Misma regla que kanban_column() en app.py, para recolocar tras un cambio sin recargar.
function columnFor(task) {
  if (task.status === "CLOSED") return "DONE";
  if (task.status === "IN_PROGRESS") return "IN_PROGRESS";
  if (task.status === "PAUSED") return "WAITING";
  if (task.planned_date && task.planned_date <= todayIso()) return "TODAY";
  return "TODO";
}

function daysOverdue(task) {
  if (task.status === "CLOSED" || !task.planned_date) return 0;
  const diff = (new Date(`${todayIso()}T00:00:00`) - new Date(`${task.planned_date}T00:00:00`)) / 86400000;
  return diff > 0 ? Math.round(diff) : 0;
}

function passesFilters(task) {
  if (filters.hiddenProjects.includes(task.project_id)) return false;
  if (filters.type && task.type !== filters.type) return false;
  if (filters.owner && task.owner_role !== filters.owner) return false;
  if (filters.date === "LATE" && daysOverdue(task) === 0) return false;
  if (filters.date === "NONE" && task.planned_date) return false;
  if (filters.date === "WEEK") {
    const [start, end] = weekRangeIso();
    if (!task.planned_date || task.planned_date < start || task.planned_date > end) return false;
  }
  const q = filters.search.trim().toLowerCase();
  if (q) {
    const haystack = `${task.title || ""} ${task.project_code || ""} ${task.project_name || ""}`.toLowerCase();
    if (!haystack.includes(q)) return false;
  }
  return true;
}

function sortCards(columnKey, list) {
  if (columnKey === "DONE") {
    return list.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  }
  return list.sort((a, b) => {
    const lateDiff = daysOverdue(b) - daysOverdue(a);
    if (lateDiff) return lateDiff;
    if (!a.planned_date) return b.planned_date ? 1 : 0;
    if (!b.planned_date) return -1;
    return a.planned_date.localeCompare(b.planned_date);
  });
}

function projectsFromTasks() {
  const byId = new Map();
  for (const task of tasks) {
    if (!byId.has(task.project_id)) {
      byId.set(task.project_id, {
        id: task.project_id,
        code: task.project_code,
        name: task.project_name,
        color: task.project_color,
      });
    }
  }
  return [...byId.values()].sort((a, b) => String(a.name || a.code).localeCompare(String(b.name || b.code), "es"));
}

function renderProjectChips() {
  const container = $("projectChips");
  container.innerHTML = "";
  const projects = projectsFromTasks();
  if (!projects.length) {
    container.innerHTML = '<span class="small muted">No hay tareas abiertas.</span>';
    return;
  }
  for (const project of projects) {
    const chip = document.createElement("button");
    chip.type = "button";
    const hidden = filters.hiddenProjects.includes(project.id);
    chip.className = `project-chip${hidden ? " off" : ""}`;
    chip.title = project.name || project.code;
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = project.color;
    chip.append(dot, document.createTextNode(project.code || project.name || "—"));
    chip.addEventListener("click", () => {
      filters.hiddenProjects = hidden
        ? filters.hiddenProjects.filter((id) => id !== project.id)
        : [...filters.hiddenProjects, project.id];
      saveFilters();
      render();
    });
    container.appendChild(chip);
  }
}

function buildCard(task) {
  const card = document.createElement("div");
  const late = daysOverdue(task);
  card.className = `kcard${late && task.status !== "CLOSED" ? " late" : ""}`;
  card.draggable = true;
  card.dataset.taskId = task.id;
  card.style.setProperty("--project-color", task.project_color);

  const project = document.createElement("div");
  project.className = "kcard-project";
  project.textContent = `${task.project_code || "—"} · ${task.project_name || ""}`;
  project.title = project.textContent;

  const title = document.createElement("div");
  title.className = "kcard-title";
  title.textContent = task.title || "(Sin título)";

  const meta = document.createElement("div");
  meta.className = "kcard-meta";
  const typeBadge = document.createElement("span");
  typeBadge.className = `kbadge ${task.type === "PP" ? "kbadge-pp" : "kbadge-task"}`;
  typeBadge.textContent = task.type === "PP" ? "PP" : "Tarea";
  const owner = document.createElement("span");
  owner.className = "kbadge kbadge-owner";
  owner.textContent = OWNER_LABELS[task.owner_role] || task.owner_role;
  const dateBadge = document.createElement("span");
  if (late) {
    dateBadge.className = "kbadge kbadge-late";
    dateBadge.textContent = `Retrasada ${late} ${late === 1 ? "día" : "días"}`;
    dateBadge.title = `Prevista ${fmtDate(task.planned_date)}`;
  } else {
    dateBadge.className = "muted";
    dateBadge.innerHTML = '<i class="bi bi-calendar3"></i> ';
    dateBadge.append(document.createTextNode(fmtDate(task.planned_date)));
  }
  meta.append(typeBadge, owner, dateBadge);

  card.append(project, title, meta);
  card.addEventListener("click", () => openEditModal(task));
  card.addEventListener("dragstart", (event) => {
    draggedTaskId = task.id;
    card.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", String(task.id));
  });
  card.addEventListener("dragend", () => {
    draggedTaskId = null;
    card.classList.remove("dragging");
  });
  return card;
}

function renderBoard() {
  const board = $("board");
  board.innerHTML = "";
  const visible = tasks.filter(passesFilters);
  for (const column of COLUMNS) {
    const col = document.createElement("section");
    col.className = `kcol${column.key === "TODAY" ? " kcol-today" : ""}`;
    col.dataset.column = column.key;
    const cards = sortCards(column.key, visible.filter((task) => columnFor(task) === column.key));

    const head = document.createElement("div");
    head.className = "kcol-head";
    const label = document.createElement("span");
    label.textContent = column.label;
    const count = document.createElement("span");
    count.className = "kcol-count";
    count.textContent = cards.length;
    head.append(label, count);

    const body = document.createElement("div");
    body.className = "kcol-body";
    if (!cards.length) {
      const empty = document.createElement("div");
      empty.className = "empty-col";
      empty.textContent = column.key === "DONE" ? "Nada cerrado en los últimos 14 días" : "Sin tarjetas";
      body.appendChild(empty);
    }
    cards.forEach((task) => body.appendChild(buildCard(task)));

    col.append(head, body);
    col.addEventListener("dragover", (event) => {
      event.preventDefault();
      col.classList.add("drag-over");
    });
    col.addEventListener("dragleave", (event) => {
      if (!col.contains(event.relatedTarget)) col.classList.remove("drag-over");
    });
    col.addEventListener("drop", async (event) => {
      event.preventDefault();
      col.classList.remove("drag-over");
      const id = Number(event.dataTransfer.getData("text/plain") || draggedTaskId);
      const task = tasks.find((t) => t.id === id);
      if (task) await moveTask(task, column.key);
    });
    board.appendChild(col);
  }
}

function render() {
  renderProjectChips();
  renderBoard();
}

function askRescheduleDate(task) {
  $("rescheduleTitle").textContent = task.title || "";
  $("rescheduleDate").value = addDaysIso(1);
  $("rescheduleError").textContent = "";
  rescheduleModal.show();
  return new Promise((resolve) => {
    rescheduleResolve = resolve;
  });
}

function finishReschedule(value) {
  const resolve = rescheduleResolve;
  rescheduleResolve = null;
  rescheduleModal.hide();
  if (resolve) resolve(value);
}

function confirmPpDateChange(task, newDate) {
  if (task.type !== "PP" || task.planned_date === newDate) return true;
  return window.confirm(
    `Vas a cambiar la fecha de este PP del ${fmtDate(task.planned_date)} al ${fmtDate(newDate)}.\n\n${task.title || ""}\n\n¿Continuar?`
  );
}

async function patchTask(task, changes) {
  const res = await fetch(`${API}/project-tasks/${task.id}/kanban`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  if (!res.ok) {
    window.alert("No se pudo mover la tarjeta.");
    return false;
  }
  Object.assign(task, changes);
  if ("status" in changes) task.updated_at = new Date().toISOString();
  return true;
}

async function moveTask(task, targetColumn) {
  const current = columnFor(task);
  if (current === targetColumn) return;
  const changes = {};
  const status = COLUMN_STATUS[targetColumn];
  if (task.status !== status) changes.status = status;

  if (targetColumn === "TODAY") {
    const today = todayIso();
    if (task.planned_date !== today) {
      if (!confirmPpDateChange(task, today)) return;
      changes.planned_date = today;
    }
  } else if (targetColumn === "TODO" && task.planned_date && task.planned_date <= todayIso()) {
    // Si se queda con fecha de hoy o pasada volvería a caer en HOY: pedimos fecha nueva.
    const newDate = await askRescheduleDate(task);
    if (newDate === undefined) return;
    changes.planned_date = newDate;
  }

  if (!Object.keys(changes).length) return;
  if (await patchTask(task, changes)) renderBoard();
}

function renderEditSubtasks(subtasks) {
  const container = $("editSubtasks");
  container.innerHTML = "";
  $("editSubtasksBlock").classList.toggle("d-none", !subtasks.length);
  subtasks.forEach((row, idx) => {
    const label = document.createElement("label");
    label.className = "d-flex align-items-center gap-2";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "form-check-input mt-0";
    input.checked = row.done;
    input.addEventListener("change", () => {
      row.done = input.checked;
    });
    label.append(input, document.createTextNode(row.text));
    container.appendChild(label);
  });
}

function renderEditNotes(notesLog) {
  const container = $("editNotesLog");
  container.innerHTML = "";
  $("editNotesBlock").classList.toggle("d-none", !notesLog.length);
  [...notesLog].reverse().forEach((entry) => {
    const item = document.createElement("div");
    item.className = "border rounded p-2";
    const when = document.createElement("div");
    when.className = "muted";
    when.textContent = fmtDateTime(entry.created_at);
    const text = document.createElement("div");
    text.style.whiteSpace = "pre-wrap";
    text.textContent = entry.notes;
    item.append(when, text);
    container.appendChild(item);
  });
}

function openEditModal(task) {
  selectedTask = task;
  const { description, subtasks } = splitDescriptionAndSubtasks(task.description);
  selectedTask.editSubtasks = subtasks;
  $("editProject").textContent = `${task.project_code || "—"} · ${task.project_name || ""}`;
  $("editProjectColor").value = task.project_color;
  $("editTitle").value = task.title || "";
  $("editType").value = task.type;
  $("editOwner").value = task.owner_role;
  $("editDate").value = task.planned_date || "";
  $("editStatus").value = task.status;
  $("editDescription").value = description;
  $("editNewNote").value = "";
  $("editError").textContent = "";
  $("editCloseTask").classList.toggle("d-none", task.status === "CLOSED");
  renderEditSubtasks(subtasks);
  renderEditNotes(task.notes_log || []);
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
    description: composeDescriptionWithSubtasks($("editDescription").value, selectedTask.editSubtasks),
  };
  if (!payload.title || !payload.description) {
    $("editError").textContent = "Título y descripción son obligatorios.";
    return;
  }
  if (payload.planned_date && !confirmPpDateChange({ ...selectedTask, type: payload.type }, payload.planned_date)) return;

  const res = await fetch(`${API}/project-tasks/${selectedTask.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    $("editError").textContent = "No se pudo guardar la tarea.";
    return;
  }
  const note = ($("editNewNote").value || "").trim();
  if (note) {
    const noteRes = await fetch(`${API}/project-tasks/${selectedTask.id}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: note }),
    });
    if (!noteRes.ok) {
      $("editError").textContent = "La tarea se guardó, pero no la nota.";
      return;
    }
  }
  editModal.hide();
  await loadTasks();
}

async function closeSelectedTask() {
  if (!selectedTask) return;
  if (await patchTask(selectedTask, { status: "CLOSED" })) {
    editModal.hide();
    renderBoard();
  }
}

async function saveProjectColor() {
  if (!selectedTask) return;
  const color = $("editProjectColor").value;
  const res = await fetch(`${API}/api/projects/${selectedTask.project_id}/color`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ color }),
  });
  if (!res.ok) {
    $("editError").textContent = "No se pudo guardar el color del proyecto.";
    return;
  }
  const data = await res.json();
  tasks.filter((t) => t.project_id === selectedTask.project_id).forEach((t) => {
    t.project_color = data.color;
  });
  render();
}

async function loadTasks() {
  const res = await fetch(`${API}/api/kanban/tasks`);
  if (!res.ok) {
    $("board").innerHTML = '<div class="text-danger">No se pudieron cargar las tareas.</div>';
    return;
  }
  tasks = await res.json();
  render();
}

function syncFilterInputs() {
  $("filterSearch").value = filters.search;
  $("filterType").value = filters.type;
  $("filterOwner").value = filters.owner;
  $("filterDate").value = filters.date;
}

function bindFilters() {
  const bind = (id, key, eventName) => {
    $(id).addEventListener(eventName, () => {
      filters[key] = $(id).value;
      saveFilters();
      renderBoard();
    });
  };
  bind("filterSearch", "search", "input");
  bind("filterType", "type", "change");
  bind("filterOwner", "owner", "change");
  bind("filterDate", "date", "change");
  $("clearFilters").addEventListener("click", () => {
    filters = { search: "", type: "", owner: "", date: "", hiddenProjects: [] };
    saveFilters();
    syncFilterInputs();
    render();
  });
  $("projectsAll").addEventListener("click", () => {
    filters.hiddenProjects = [];
    saveFilters();
    render();
  });
  $("projectsNone").addEventListener("click", () => {
    filters.hiddenProjects = projectsFromTasks().map((p) => p.id);
    saveFilters();
    render();
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  editModal = new bootstrap.Modal($("editModal"));
  rescheduleModal = new bootstrap.Modal($("rescheduleModal"));
  $("rescheduleModal").addEventListener("hidden.bs.modal", () => {
    if (rescheduleResolve) finishReschedule(undefined);
  });
  document.querySelectorAll("[data-reschedule]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const choice = btn.dataset.reschedule;
      if (choice === "tomorrow") finishReschedule(addDaysIso(1));
      else if (choice === "monday") finishReschedule(nextMondayIso());
      else finishReschedule(null);
    });
  });
  $("rescheduleCustom").addEventListener("click", () => {
    const value = $("rescheduleDate").value;
    if (!value || value <= todayIso()) {
      $("rescheduleError").textContent = "Elige una fecha posterior a hoy.";
      return;
    }
    finishReschedule(value);
  });
  $("editSave").addEventListener("click", saveEdit);
  $("editCloseTask").addEventListener("click", closeSelectedTask);
  $("editProjectColor").addEventListener("change", saveProjectColor);

  syncFilterInputs();
  bindFilters();
  await loadTasks();
});
