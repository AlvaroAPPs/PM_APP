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

const LAST_PROJECT_KEY = "kanban.lastProject.v1";

let tasks = [];
let allProjects = [];
let quickAdd = null; // { column, projectId, type, owner } mientras el formulario rápido está abierto
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
    if (column.key !== "DONE") body.appendChild(buildQuickAdd(column.key));
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

function loadLastProjectId() {
  try {
    return Number(localStorage.getItem(LAST_PROJECT_KEY) || 0);
  } catch {
    return 0;
  }
}

function defaultQuickAddProjectId() {
  // Con un solo proyecto visible en el filtro, se crea en ese; si no, en el último usado.
  const visible = projectsFromTasks().filter((p) => !filters.hiddenProjects.includes(p.id));
  if (visible.length === 1) return visible[0].id;
  const last = loadLastProjectId();
  if (allProjects.some((p) => p.id === last)) return last;
  return visible[0]?.id || 0;
}

function openQuickAdd(columnKey) {
  quickAdd = {
    column: columnKey,
    projectId: quickAdd?.projectId || defaultQuickAddProjectId(),
    type: quickAdd?.type || "TASK",
    owner: quickAdd?.owner || "PM",
    focus: true,
  };
  renderBoard();
}

function buildQuickAdd(columnKey) {
  if (!quickAdd || quickAdd.column !== columnKey) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "quick-add-btn";
    btn.innerHTML = '<i class="bi bi-plus-lg"></i> Añadir tarjeta';
    btn.addEventListener("click", () => openQuickAdd(columnKey));
    return btn;
  }

  const form = document.createElement("form");
  form.className = "quick-add-form";

  const title = document.createElement("input");
  title.className = "form-control form-control-sm";
  title.placeholder = "Título y Enter";
  title.required = true;

  const project = buildProjectPicker();

  const row = document.createElement("div");
  row.className = "d-flex gap-1";
  const type = document.createElement("select");
  type.className = "form-select form-select-sm";
  type.innerHTML = '<option value="TASK">Tarea</option><option value="PP">PP</option>';
  type.value = quickAdd.type;
  type.addEventListener("change", () => {
    quickAdd.type = type.value;
  });
  const owner = document.createElement("select");
  owner.className = "form-select form-select-sm";
  owner.innerHTML = Object.entries(OWNER_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  owner.value = quickAdd.owner;
  owner.addEventListener("change", () => {
    quickAdd.owner = owner.value;
  });
  row.append(type, owner);

  const actions = document.createElement("div");
  actions.className = "d-flex gap-1 align-items-center";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "btn btn-sm btn-dark";
  submit.textContent = "Añadir";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "btn btn-sm btn-link text-secondary";
  cancel.textContent = "Cancelar";
  cancel.addEventListener("click", closeQuickAdd);
  const error = document.createElement("span");
  error.className = "text-danger small";
  actions.append(submit, cancel, error);

  form.append(title, project, row, actions);
  form.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeQuickAdd();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = title.value.trim();
    if (!text) return;
    if (!quickAdd.projectId) {
      error.textContent = "Elige un proyecto de la lista.";
      return;
    }
    submit.disabled = true;
    error.textContent = "";
    if (await createQuickTask(columnKey, text)) {
      quickAdd.focus = true;
      await loadTasks();
    } else {
      submit.disabled = false;
      error.textContent = "No se pudo crear.";
    }
  });
  if (quickAdd.focus) {
    // Solo al abrir o tras crear: otros repintados (p. ej. al escribir en Buscar) no deben robar el foco.
    quickAdd.focus = false;
    setTimeout(() => title.focus(), 0);
  }
  return form;
}

function closeQuickAdd() {
  quickAdd = null;
  renderBoard();
}

async function createQuickTask(columnKey, title) {
  const payload = {
    project_id: quickAdd.projectId,
    type: quickAdd.type,
    owner_role: quickAdd.owner,
    status: COLUMN_STATUS[columnKey],
    planned_date: columnKey === "TODAY" || columnKey === "IN_PROGRESS" ? todayIso() : null,
    title,
    description: title,
  };
  const res = await fetch(`${API}/project-tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) return false;
  try {
    localStorage.setItem(LAST_PROJECT_KEY, String(quickAdd.projectId));
  } catch {
    /* sin almacenamiento */
  }
  // Que la tarjeta nueva no quede oculta por el filtro de proyectos.
  if (filters.hiddenProjects.includes(quickAdd.projectId)) {
    filters.hiddenProjects = filters.hiddenProjects.filter((id) => id !== quickAdd.projectId);
    saveFilters();
  }
  return true;
}

function projectLabel(project) {
  return project ? `${project.project_code} · ${project.project_name || ""}` : "";
}

function normalizeText(value) {
  // Sin tildes ni puntuación: "ALIMERKA, S.A." se encuentra con "alimerka sa".
  return String(value || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[.,'´`]/g, "")
    .replace(/[^a-z0-9ñ]+/g, " ")
    .trim();
}

// Busca por código o nombre (sin tildes, varias palabras). Prioriza código que empieza igual
// y, a igualdad, los proyectos que ya tienen tarjetas en el tablero.
function searchProjects(query, limit = 8) {
  const words = normalizeText(query).split(/\s+/).filter(Boolean);
  const withTasks = new Set(tasks.map((t) => t.project_id));
  const scored = [];
  for (const p of allProjects) {
    const code = normalizeText(p.project_code);
    const name = normalizeText(p.project_name);
    const haystack = `${code} ${name}`;
    if (!words.every((w) => haystack.includes(w))) continue;
    let score = 2;
    if (words.length && code.startsWith(words[0])) score = 0;
    else if (words.length && name.split(" ").some((part) => part.startsWith(words[0]))) score = 1;
    if (!withTasks.has(p.id)) score += 0.5;
    scored.push({ p, score });
  }
  scored.sort((a, b) => a.score - b.score || String(a.p.project_code).localeCompare(String(b.p.project_code)));
  return scored.slice(0, limit).map((row) => row.p);
}

function buildProjectPicker() {
  const wrap = document.createElement("div");
  wrap.className = "project-picker";
  const input = document.createElement("input");
  input.className = "form-control form-control-sm";
  input.placeholder = "Proyecto: escribe código o nombre";
  input.autocomplete = "off";
  input.value = projectLabel(allProjects.find((p) => p.id === quickAdd.projectId));
  const list = document.createElement("div");
  list.className = "project-suggest d-none";
  wrap.append(input, list);

  let results = [];
  let active = 0;

  const choose = (p) => {
    quickAdd.projectId = p.id;
    input.value = projectLabel(p);
    list.classList.add("d-none");
  };

  const renderList = () => {
    list.innerHTML = "";
    if (!results.length) {
      list.innerHTML = '<div class="project-suggest-empty">Sin coincidencias</div>';
    }
    results.forEach((p, idx) => {
      const item = document.createElement("div");
      item.className = `project-suggest-item${idx === active ? " active" : ""}`;
      const code = document.createElement("strong");
      code.textContent = p.project_code;
      item.append(code, document.createTextNode(` ${p.project_name || ""}`));
      // mousedown para elegir antes de que el blur cierre la lista
      item.addEventListener("mousedown", (event) => {
        event.preventDefault();
        choose(p);
      });
      list.appendChild(item);
    });
    list.classList.remove("d-none");
  };

  const refresh = () => {
    results = searchProjects(input.value);
    active = 0;
    renderList();
  };

  input.addEventListener("focus", () => {
    input.select();
    results = searchProjects("");
    active = 0;
    renderList();
  });
  input.addEventListener("input", () => {
    quickAdd.projectId = 0;
    refresh();
  });
  input.addEventListener("blur", () => list.classList.add("d-none"));
  input.addEventListener("keydown", (event) => {
    const open = !list.classList.contains("d-none");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) return refresh();
      if (!results.length) return;
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
      renderList();
    } else if (event.key === "Enter" && open && results[active]) {
      event.preventDefault();
      choose(results[active]);
      input.closest("form").querySelector("input").focus();
    } else if (event.key === "Escape" && open) {
      event.stopPropagation();
      list.classList.add("d-none");
    }
  });
  return wrap;
}

async function loadAllProjects() {
  const res = await fetch(`${API}/projects/non-historical?limit=5000`);
  allProjects = res.ok ? await res.json() : [];
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

function addEditSubtaskRow(text = "", done = false, focus = false) {
  const row = document.createElement("div");
  row.className = "input-group input-group-sm";

  const checkWrapper = document.createElement("span");
  checkWrapper.className = "input-group-text";
  const check = document.createElement("input");
  check.className = "form-check-input mt-0 subtaskDone";
  check.type = "checkbox";
  check.checked = !!done;
  checkWrapper.appendChild(check);

  const input = document.createElement("input");
  input.type = "text";
  input.className = "form-control subtaskText";
  input.placeholder = "Escribe la subtarea...";
  input.value = String(text || "");
  // Enter crea la fila siguiente para ir apuntando checks seguidos.
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addEditSubtaskRow("", false, true);
  });

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "btn btn-outline-danger";
  removeBtn.textContent = "Quitar";
  removeBtn.addEventListener("click", () => row.remove());

  row.append(checkWrapper, input, removeBtn);
  $("editSubtasks").appendChild(row);
  if (focus) input.focus();
}

function renderEditSubtasks(subtasks) {
  $("editSubtasks").innerHTML = "";
  subtasks.forEach((row) => addEditSubtaskRow(row.text, row.done));
  if (!subtasks.length) addEditSubtaskRow();
}

function readEditSubtasks() {
  return [...$("editSubtasks").querySelectorAll(".input-group")]
    .map((row) => ({
      done: row.querySelector(".subtaskDone").checked,
      text: (row.querySelector(".subtaskText").value || "").trim(),
    }))
    .filter((row) => row.text);
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
    description: composeDescriptionWithSubtasks($("editDescription").value, readEditSubtasks()),
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

async function deleteSelectedTask() {
  if (!selectedTask) return;
  const label = selectedTask.type === "PP" ? "este PP" : "esta tarea";
  const ok = window.confirm(
    `¿Eliminar ${label} definitivamente?\n\n${selectedTask.title || ""}\n\nSe borrarán también sus notas y subtareas y no se puede deshacer. ` +
      "Si solo está terminada, usa «Marcar como hecha»."
  );
  if (!ok) return;
  const res = await fetch(`${API}/project-tasks/${selectedTask.id}`, { method: "DELETE" });
  if (!res.ok) {
    $("editError").textContent = "No se pudo eliminar.";
    return;
  }
  const deletedId = selectedTask.id;
  tasks = tasks.filter((t) => t.id !== deletedId);
  selectedTask = null;
  editModal.hide();
  render();
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
  $("editDeleteTask").addEventListener("click", deleteSelectedTask);
  $("editAddSubtask").addEventListener("click", () => addEditSubtaskRow("", false, true));
  $("editProjectColor").addEventListener("change", saveProjectColor);

  syncFilterInputs();
  bindFilters();
  await loadAllProjects();
  await loadTasks();
});
