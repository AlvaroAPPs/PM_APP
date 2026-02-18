const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

let viewMode = "month";
let anchorDate = new Date();
let selectedDate = new Date();
let calendarTasks = [];
let allOpenTasks = [];
let weekTasks = [];
let weekPp = [];
let weekNotes = [];
let selectedTask = null;
let editingNote = null;
let detailModal = null;
let editModal = null;
let noteModal = null;
let createTaskModal = null;
const SUBTASKS_MARKER = "\n\n---SUBTASKS---\n";

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

function splitDescriptionAndSubtasks(rawDescription) {
  const text = rawDescription || "";
  const markerIdx = text.indexOf(SUBTASKS_MARKER);
  if (markerIdx < 0) return { description: text, subtasks: [] };
  const description = text.slice(0, markerIdx).trimEnd();
  const tail = text.slice(markerIdx + SUBTASKS_MARKER.length);
  const subtasks = tail
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("[ ] ") || line.startsWith("[x] ") || line.startsWith("[X] "))
    .map((line) => ({ done: line[1].toLowerCase() === "x", text: line.slice(4).trim() }))
    .filter((row) => row.text.length > 0);
  return { description, subtasks };
}

function composeDescriptionWithSubtasks(description, subtasks) {
  const cleanDescription = (description || "").trim();
  const cleanSubtasks = (subtasks || []).filter((row) => row.text && row.text.trim());
  if (!cleanSubtasks.length) return cleanDescription;
  const lines = cleanSubtasks.map((row) => `[${row.done ? "x" : " "}] ${row.text.trim()}`);
  return `${cleanDescription}${SUBTASKS_MARKER}${lines.join("\n")}`;
}

function buildEditChecklistItem(text = "", done = false) {
  const wrap = document.createElement("div");
  wrap.className = "note-checklist-item";
  wrap.innerHTML = `
    <input type="checkbox" class="form-check-input" ${done ? "checked" : ""} />
    <input type="text" class="form-control form-control-sm" value="${String(text || "").replace(/"/g, "&quot;")}" placeholder="Sub-tarea" />
    <button type="button" class="btn btn-sm btn-outline-danger">×</button>
  `;
  wrap.querySelector("button").addEventListener("click", () => wrap.remove());
  return wrap;
}

function readEditChecklist() {
  const rows = [...$("editChecklist").querySelectorAll(".note-checklist-item")];
  return rows.map((row) => ({
    done: Boolean(row.querySelector('input[type="checkbox"]').checked),
    text: (row.querySelector('input[type="text"]').value || "").trim(),
  })).filter((row) => row.text);
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

function inSelectedWeek(dateValue) {
  const d = parseIsoDate(dateValue);
  if (!d) return false;
  const start = startOfWeek(selectedDate);
  const end = endOfWeek(selectedDate);
  return d >= start && d <= end;
}

function getVisibleCalendarRange() {
  if (viewMode === "week") {
    return { start: startOfWeek(anchorDate), end: endOfWeek(anchorDate) };
  }
  const first = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1);
  const start = startOfWeek(first);
  const end = new Date(start);
  end.setDate(start.getDate() + 41);
  return { start, end };
}

async function fetchTasksInRange(start, end, includeClosed) {
  const params = new URLSearchParams();
  params.set("start_date", toIsoDate(start));
  params.set("end_date", toIsoDate(end));
  params.set("include_closed", includeClosed ? "true" : "false");
  const res = await fetch(`${API}/project-tasks?${params.toString()}`);
  return res.ok ? res.json() : [];
}

async function fetchAllOpenTasks() {
  const res = await fetch(`${API}/project-tasks?include_closed=false`);
  allOpenTasks = res.ok ? await res.json() : [];
}

async function fetchNotesWithFallback(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (res.status !== 404) return res;
  const fallbackPath = path.replace("/project-notes", "/notes");
  return fetch(`${API}${fallbackPath}`, options);
}

async function fetchWeekNotes() {
  const start = startOfWeek(selectedDate);
  const end = endOfWeek(selectedDate);
  const params = new URLSearchParams();
  params.set("start_date", toIsoDate(start));
  params.set("end_date", toIsoDate(end));
  const res = await fetchNotesWithFallback(`/project-notes?${params.toString()}`);
  weekNotes = res.ok ? await res.json() : [];
}

function splitWeekSidebarData() {
  const weekStart = startOfWeek(selectedDate);
  const inWeekOrPrevious = (plannedDate) => {
    if (!plannedDate) return true;
    if (inSelectedWeek(plannedDate)) return true;
    const parsed = parseIsoDate(plannedDate);
    return parsed ? parsed < weekStart : false;
  };

  const taskItems = allOpenTasks.filter((t) => t.type === "TASK" && inWeekOrPrevious(t.planned_date));
  const ppItems = allOpenTasks.filter((t) => t.type === "PP" && inWeekOrPrevious(t.planned_date));
  weekTasks = taskItems;
  weekPp = ppItems;
}

async function fetchCalendarTasks() {
  const { start, end } = getVisibleCalendarRange();
  calendarTasks = await fetchTasksInRange(start, end, false);
  renderCalendar();
}

async function refreshCalendarData() {
  await Promise.all([fetchCalendarTasks(), fetchAllOpenTasks(), fetchWeekNotes()]);
  splitWeekSidebarData();
  renderWeekSidebar();
}

function renderListBlock(containerId, items, emptyText, onClick, rightText) {
  const container = $(containerId);
  if (!container) return;
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = `<div class="muted small">${emptyText}</div>`;
    return;
  }
  for (const item of items) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "list-group-item list-group-item-action";
    btn.innerHTML = `
      <div class="d-flex justify-content-between gap-2">
        <div>
          <div class="fw-semibold">${item.title || "(Sin título)"}</div>
          <div class="small muted">${item.project_code || ""}${item.project_name ? ` · ${item.project_name}` : ""}</div>
        </div>
        <div class="text-end small">${rightText(item)}</div>
      </div>
    `;
    btn.addEventListener("click", () => onClick(item));
    container.appendChild(btn);
  }
}

function renderWeekSidebar() {
  const start = startOfWeek(selectedDate);
  const end = endOfWeek(selectedDate);
  $("weekLabel").textContent = `${fmtDate(start)} - ${fmtDate(end)}`;

  renderListBlock("weekTasks", weekTasks, "No tasks", openTaskDetail, (item) => fmtDate(item.planned_date));
  renderListBlock("weekPp", weekPp, "No PP", openTaskDetail, (item) => fmtDate(item.planned_date));
  renderListBlock("weekNotes", weekNotes, "No notes this week", openNoteModal, (item) => fmtDate(item.date));
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
  for (const task of calendarTasks) {
    if (!task.planned_date || task.status === "CLOSED") continue;
    const key = task.planned_date;
    if (!tasksByDay.has(key)) tasksByDay.set(key, []);
    tasksByDay.get(key).push(task);
  }

  const notesByDay = new Set(weekNotes.map((n) => n.date));

  if (viewMode === "week") {
    const start = startOfWeek(anchorDate);
    for (let i = 0; i < 7; i += 1) {
      const day = new Date(start);
      day.setDate(start.getDate() + i);
      grid.appendChild(buildDayCell(day, tasksByDay, notesByDay, false));
    }
    return;
  }

  const first = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1);
  const start = startOfWeek(first);
  for (let i = 0; i < 42; i += 1) {
    const day = new Date(start);
    day.setDate(start.getDate() + i);
    const outside = day.getMonth() !== anchorDate.getMonth();
    grid.appendChild(buildDayCell(day, tasksByDay, notesByDay, outside));
  }
}

function buildDayCell(day, tasksByDay, notesByDay, outsideMonth) {
  const cell = document.createElement("div");
  cell.className = "calendar-cell text-start";
  if (sameDay(day, selectedDate)) cell.classList.add("active");
  if (outsideMonth) cell.classList.add("opacity-50");

  const key = toIsoDate(day);
  const tasks = tasksByDay.get(key) || [];

  const num = document.createElement("div");
  num.className = "num d-flex align-items-center";
  num.textContent = String(day.getDate());
  if (notesByDay.has(key)) {
    const marker = document.createElement("span");
    marker.className = "task-chip-note-marker";
    marker.title = "Hay notas";
    num.appendChild(marker);
  }
  cell.appendChild(num);

  const list = document.createElement("div");
  list.className = "mt-1 d-flex flex-column gap-1";

  const visible = tasks.slice(0, 3);
  for (const task of visible) {
    const chip = document.createElement("button");
    chip.type = "button";
    const chipClass = task.type === "PP" ? "task-chip-pp" : "task-chip-task";
    chip.className = `task-chip ${chipClass}`;
    chip.textContent = task.title || "(Sin título)";
    chip.title = `${typeLabel(task.type)} · ${task.project_code || "—"}`;
    chip.addEventListener("click", (event) => {
      event.stopPropagation();
      openTaskDetail(task);
    });
    list.appendChild(chip);
  }

  if (tasks.length > 3) {
    const more = document.createElement("span");
    more.className = "small muted";
    more.textContent = `+${tasks.length - 3} más`;
    list.appendChild(more);
  }

  cell.appendChild(list);
  cell.addEventListener("click", async () => {
    selectedDate = new Date(day);
    if (viewMode === "month" && day.getMonth() !== anchorDate.getMonth()) {
      anchorDate = new Date(day.getFullYear(), day.getMonth(), 1);
      await fetchCalendarTasks();
    }
    await refreshCalendarData();
    renderCalendar();
  });

  return cell;
}

function openTaskDetail(task) {
  selectedTask = task;
  const parsed = splitDescriptionAndSubtasks(task.description || "");
  $("detailProject").textContent = `${task.project_code || "—"} - ${task.project_name || "—"}`;
  $("detailTitle").textContent = task.title || "—";
  $("detailType").textContent = typeLabel(task.type);
  $("detailStatus").textContent = statusLabel(task.status);
  $("detailOwner").textContent = task.owner_role || "—";
  $("detailDate").textContent = fmtDate(task.planned_date);
  $("detailDescription").textContent = parsed.description || "—";

  const checklistEl = $("detailChecklist");
  if (!parsed.subtasks.length) {
    checklistEl.textContent = "—";
  } else {
    checklistEl.innerHTML = `<ul class="detail-checklist">${parsed.subtasks
      .map((item) => `<li><span class="check-icon">${item.done ? "✅" : "⬜"}</span><span>${item.text}</span></li>`)
      .join("")}</ul>`;
  }

  detailModal.show();
}

function openEditModal() {
  if (!selectedTask) return;
  const parsed = splitDescriptionAndSubtasks(selectedTask.description || "");
  $("editTitle").value = selectedTask.title || "";
  $("editType").value = selectedTask.type || "TASK";
  $("editOwner").value = selectedTask.owner_role || "PM";
  $("editDate").value = selectedTask.planned_date || "";
  $("editStatus").value = selectedTask.status || "OPEN";
  $("editDescription").value = parsed.description || "";
  const box = $("editChecklist");
  box.innerHTML = "";
  if (parsed.subtasks.length) {
    parsed.subtasks.forEach((row) => box.appendChild(buildEditChecklistItem(row.text, row.done)));
  } else {
    box.appendChild(buildEditChecklistItem());
  }
  $("editError").textContent = "";
  editModal.show();
}

function buildChecklistItem(text = "", done = false) {
  const wrap = document.createElement("div");
  wrap.className = "note-checklist-item";
  wrap.innerHTML = `
    <input type="checkbox" class="form-check-input" ${done ? "checked" : ""} />
    <input type="text" class="form-control form-control-sm" value="${text.replace(/"/g, "&quot;")}" placeholder="Item" />
    <button type="button" class="btn btn-sm btn-outline-danger">×</button>
  `;
  wrap.querySelector("button").addEventListener("click", () => wrap.remove());
  return wrap;
}

function openNoteModal(note = null) {
  editingNote = note;
  $("noteModalTitle").textContent = note ? "Editar nota" : "Nueva nota";
  $("noteTitle").value = note?.title || "";
  $("noteComment").value = note?.comment || "";
  $("noteDate").value = note?.date || toIsoDate(new Date());
  $("noteError").textContent = "";
  $("deleteNote").classList.toggle("d-none", !note);
  const checklist = $("noteChecklist");
  checklist.innerHTML = "";
  const items = Array.isArray(note?.checklist) && note.checklist.length ? note.checklist : [{ text: "", done: false }];
  items.forEach((item) => checklist.appendChild(buildChecklistItem(item.text || "", Boolean(item.done))));
  noteModal.show();
}

function readChecklistFromUi() {
  const rows = [...$("noteChecklist").querySelectorAll(".note-checklist-item")];
  return rows.map((row) => ({
    text: (row.querySelector('input[type="text"]').value || "").trim(),
    done: Boolean(row.querySelector('input[type="checkbox"]').checked),
  })).filter((item) => item.text);
}

async function deleteNote() {
  if (!editingNote) return;
  if (!window.confirm("¿Eliminar esta nota?")) return;
  const path = `/project-notes/${editingNote.id}`;
  const res = await fetchNotesWithFallback(path, { method: "DELETE" });
  if (!res.ok) {
    let detail = "";
    try {
      const payload = await res.json();
      detail = payload?.detail ? ` (${payload.detail})` : "";
    } catch (_e) {
      detail = "";
    }
    $("noteError").textContent = `No se pudo eliminar la nota${detail}.`;
    return;
  }
  noteModal.hide();
  await refreshCalendarData();
}

async function saveNote() {
  const payload = {
    title: ($("noteTitle").value || "").trim(),
    comment: ($("noteComment").value || "").trim(),
    date: $("noteDate").value,
    checklist: readChecklistFromUi(),
  };
  if (!payload.title || !payload.date) {
    $("noteError").textContent = "Título y fecha son obligatorios.";
    return;
  }
  const path = editingNote ? `/project-notes/${editingNote.id}` : `/project-notes`;
  const method = editingNote ? "PUT" : "POST";
  const res = await fetchNotesWithFallback(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  if (!res.ok) {
    let detail = "";
    try {
      const payload = await res.json();
      detail = payload?.detail ? ` (${payload.detail})` : "";
    } catch (_e) {
      detail = "";
    }
    $("noteError").textContent = `No se pudo guardar la nota${detail}.`;
    return;
  }
  noteModal.hide();
  await refreshCalendarData();
}

async function saveEdit() {
  if (!selectedTask) return;
  const payload = {
    title: ($("editTitle").value || "").trim(),
    type: $("editType").value,
    owner_role: $("editOwner").value,
    planned_date: $("editDate").value || null,
    status: $("editStatus").value,
    description: composeDescriptionWithSubtasks(($("editDescription").value || "").trim(), readEditChecklist()),
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
  await refreshCalendarData();
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
  await refreshCalendarData();
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

async function moveRange(step) {
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
  await refreshCalendarData();
}

async function setView(mode) {
  viewMode = mode;
  $("viewMonth").className = mode === "month" ? "btn btn-dark" : "btn btn-outline-dark";
  $("viewWeek").className = mode === "week" ? "btn btn-dark" : "btn btn-outline-dark";
  await refreshCalendarData();
}

async function searchProjects(query) {
  if (!query || query.trim().length < 1) return [];
  const res = await fetch(`${API}/projects/search?q=${encodeURIComponent(query.trim())}`);
  return res.ok ? res.json() : [];
}

function renderCreateProjectOptions(rows) {
  const select = $("createProject");
  if (!select) return;
  select.innerHTML = "";
  for (const row of rows) {
    const opt = document.createElement("option");
    opt.value = String(row.id);
    opt.textContent = `${row.project_code || "—"} - ${row.project_name || "—"}`;
    select.appendChild(opt);
  }
}

async function setupCreateProjectPicker() {
  const searchInput = $("createProjectSearch");
  if (!searchInput) return;
  renderCreateProjectOptions([]);
  let timer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const rows = await searchProjects(searchInput.value || "");
      renderCreateProjectOptions(rows);
    }, 250);
  });
}

function buildCreateChecklistItem(text = "", done = false) {
  const wrap = document.createElement("div");
  wrap.className = "note-checklist-item";
  wrap.innerHTML = `
    <input type="checkbox" class="form-check-input" ${done ? "checked" : ""} />
    <input type="text" class="form-control form-control-sm" value="${String(text || "").replace(/"/g, "&quot;")}" placeholder="Tarea interna" />
    <button type="button" class="btn btn-sm btn-outline-danger">×</button>
  `;
  wrap.querySelector("button").addEventListener("click", () => wrap.remove());
  return wrap;
}

function readCreateChecklist() {
  const rows = [...$("createChecklist").querySelectorAll(".note-checklist-item")];
  return rows.map((row) => ({
    done: Boolean(row.querySelector('input[type="checkbox"]').checked),
    text: (row.querySelector('input[type="text"]').value || "").trim(),
  })).filter((item) => item.text);
}

function composeDescriptionWithChecklist(description, checklist) {
  const cleanDescription = (description || "").trim();
  const cleanChecklist = (checklist || []).filter((item) => item.text && item.text.trim());
  if (!cleanChecklist.length) return cleanDescription;
  return composeDescriptionWithSubtasks(cleanDescription, cleanChecklist);
}

async function saveCreateTask() {
  const checklist = readCreateChecklist();
  const payload = {
    project_id: Number($("createProject").value || 0),
    type: $("createType").value,
    owner_role: $("createOwner").value,
    planned_date: $("createDate").value || null,
    status: $("createStatus").value,
    title: ($("createTitle").value || "").trim(),
    description: composeDescriptionWithChecklist(($("createDescription").value || "").trim(), checklist),
  };
  if (!payload.project_id || !payload.title || !payload.description) {
    $("createTaskError").textContent = "Proyecto, título y descripción son obligatorios (busca y selecciona un proyecto).";
    return;
  }
  const res = await fetch(`${API}/project-tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const err = await res.json();
      detail = err?.detail ? ` (${err.detail})` : "";
    } catch (_e) {
      detail = "";
    }
    $("createTaskError").textContent = `No se pudo crear${detail}.`;
    return;
  }
  createTaskModal.hide();
  await refreshCalendarData();
}

function openCreateTaskModal(type) {
  $("createTaskError").textContent = "";
  $("createType").value = type;
  $("createOwner").value = "PM";
  $("createStatus").value = "OPEN";
  $("createDate").value = toIsoDate(selectedDate);
  $("createTitle").value = "";
  $("createDescription").value = "";
  $("createProjectSearch").value = "";
  renderCreateProjectOptions([]);
  const checklistBox = $("createChecklist");
  checklistBox.innerHTML = "";
  checklistBox.appendChild(buildCreateChecklistItem());
  createTaskModal.show();
}

function openCreateNoteModal() {
  openNoteModal(null);
}


document.addEventListener("DOMContentLoaded", async () => {
  detailModal = new bootstrap.Modal($("taskDetailModal"));
  editModal = new bootstrap.Modal($("taskEditModal"));
  noteModal = new bootstrap.Modal($("noteEditModal"));
  createTaskModal = new bootstrap.Modal($("createTaskModal"));
  await setupCreateProjectPicker();

  $("viewMonth")?.addEventListener("click", () => setView("month"));
  $("viewWeek")?.addEventListener("click", () => setView("week"));
  $("prevRange")?.addEventListener("click", () => moveRange(-1));
  $("nextRange")?.addEventListener("click", () => moveRange(1));
  $("todayRange")?.addEventListener("click", async () => {
    anchorDate = new Date();
    selectedDate = new Date();
    await refreshCalendarData();
  });

  $("createTaskOption")?.addEventListener("click", () => openCreateTaskModal("TASK"));
  $("createPpOption")?.addEventListener("click", () => openCreateTaskModal("PP"));
  $("createNoteOption")?.addEventListener("click", openCreateNoteModal);
  $("detailEdit")?.addEventListener("click", openEditModal);
  $("saveEditTask")?.addEventListener("click", saveEdit);
  $("addEditChecklistItem")?.addEventListener("click", () => $("editChecklist").appendChild(buildEditChecklistItem()));
  $("detailClose")?.addEventListener("click", closeTask);
  $("detailNavigate")?.addEventListener("click", navigateTask);
  $("detailProjectBtn")?.addEventListener("click", goProject);
  $("addChecklistItem")?.addEventListener("click", () => $("noteChecklist").appendChild(buildChecklistItem()));
  $("saveNote")?.addEventListener("click", saveNote);
  $("deleteNote")?.addEventListener("click", deleteNote);
  $("saveCreateTask")?.addEventListener("click", saveCreateTask);
  $("addCreateChecklistItem")?.addEventListener("click", () => $("createChecklist").appendChild(buildCreateChecklistItem()));
  $("noteEditModal")?.addEventListener("hidden.bs.modal", () => { editingNote = null; });

  await refreshCalendarData();
});
