const API = window.location.origin;
const $ = (id) => document.getElementById(id);

let lockedProject = false;
let newTaskModal = null;
let editingTaskId = null;

function fmtDate(v) {
  if (!v) return "—";
  const d = new Date(`${v}T00:00:00`);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("es-ES");
}

function statusLabel(status) {
  const map = { OPEN: "Abierta", IN_PROGRESS: "Proceso", PAUSED: "Parada", CLOSED: "Cerrada" };
  return map[status] || status;
}

function typeLabel(type) {
  return type === "PP" ? "PP" : "Tarea";
}

function goBack() {
  if (window.history.length > 1) {
    window.history.back();
    return;
  }
  window.location.href = "/";
}

async function searchProjects(query) {
  if (!query || query.trim().length < 1) return [];
  const res = await fetch(`${API}/projects/search?q=${encodeURIComponent(query.trim())}`);
  if (!res.ok) return [];
  return res.json();
}

function renderProjectOptions(options) {
  const select = $("projectSelect");
  if (!select) return;
  select.innerHTML = "";
  for (const p of options) {
    const opt = document.createElement("option");
    opt.value = String(p.id);
    opt.textContent = `${p.project_code} - ${p.project_name}`;
    select.appendChild(opt);
  }
}

async function loadTasks() {
  const showClosed = $("showClosed")?.checked ? "true" : "false";
  const q = ($("listProjectFilter")?.value || "").trim();
  const status = $("listStatusFilter")?.value || "";
  const params = new URLSearchParams();
  params.set("include_closed", showClosed);
  if (q) params.set("q", q);
  if (status) params.set("status", status);

  const res = await fetch(`${API}/project-tasks?${params.toString()}`);
  const rows = res.ok ? await res.json() : [];
  const body = $("tasksBody");
  if (!body) return;
  body.innerHTML = "";

  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7" class="muted">No hay tareas.</td></tr>';
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    const projectLink = `/estado-proyecto?q=${encodeURIComponent(row.project_code || "")}`;
    tr.innerHTML = `
      <td>
        <div><a href="${projectLink}" class="text-decoration-none">${row.project_name || "—"}</a></div>
        <div class="text-muted small">${row.project_code || "—"}</div>
      </td>
      <td>${typeLabel(row.type)}</td>
      <td>${row.owner_role}</td>
      <td>${fmtDate(row.planned_date)}</td>
      <td><span class="badge text-bg-light border">${statusLabel(row.status)}</span></td>
      <td>${row.description || ""}</td>
      <td class="text-end"></td>
    `;

    const actionsTd = tr.querySelector("td:last-child");

    const edit = document.createElement("button");
    edit.className = "btn btn-sm btn-outline-secondary me-1";
    edit.textContent = "Editar";
    edit.addEventListener("click", () => openEditModal(row));
    actionsTd.appendChild(edit);

    if (row.status !== "CLOSED") {
      const close = document.createElement("button");
      close.className = "btn btn-sm btn-outline-danger me-1";
      close.textContent = "Cerrar";
      close.addEventListener("click", async () => {
        await fetch(`${API}/project-tasks/${row.id}/status`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "CLOSED" }),
        });
        loadTasks();
      });
      actionsTd.appendChild(close);
    } else {
      const reopen = document.createElement("button");
      reopen.className = "btn btn-sm btn-outline-primary me-1";
      reopen.textContent = "Reabrir";
      reopen.addEventListener("click", async () => {
        await fetch(`${API}/project-tasks/${row.id}/status`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "OPEN" }),
        });
        loadTasks();
      });
      actionsTd.appendChild(reopen);
    }
  }
}

function setModalDefaults() {
  editingTaskId = null;
  $("taskModalTitle").textContent = "Nueva Tarea / PP";
  $("saveTask").textContent = "Guardar";
  $("taskStatus").value = "OPEN";
  $("taskType").value = "TASK";
  $("ownerRole").value = "PM";
  $("plannedDate").value = "";
  $("taskDescription").value = "";
  $("taskFormError").textContent = "";
}

function openEditModal(row) {
  editingTaskId = row.id;
  $("taskModalTitle").textContent = "Editar Tarea / PP";
  $("saveTask").textContent = "Guardar cambios";
  $("projectSelect").value = String(row.project_id);
  $("taskType").value = row.type || "TASK";
  $("ownerRole").value = row.owner_role || "PM";
  $("plannedDate").value = row.planned_date || "";
  $("taskStatus").value = row.status || "OPEN";
  $("taskDescription").value = row.description || "";
  $("taskFormError").textContent = "";
  newTaskModal.show();
}

async function submitTask() {
  const projectId = Number($("projectSelect")?.value || 0);
  const payload = {
    project_id: projectId,
    type: $("taskType")?.value,
    owner_role: $("ownerRole")?.value,
    planned_date: $("plannedDate")?.value || null,
    status: $("taskStatus")?.value || "OPEN",
    description: ($("taskDescription")?.value || "").trim(),
  };

  if (!payload.project_id || !payload.type || !payload.status || !payload.description) {
    $("taskFormError").textContent = "Proyecto, tipo, estado y descripción son obligatorios.";
    return;
  }

  const method = editingTaskId ? "PUT" : "POST";
  const url = editingTaskId ? `${API}/project-tasks/${editingTaskId}` : `${API}/project-tasks`;

  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    $("taskFormError").textContent = "No se pudo guardar la tarea.";
    return;
  }

  setModalDefaults();
  newTaskModal.hide();
  loadTasks();
}

async function setupProjectPicker() {
  const params = new URLSearchParams(window.location.search);
  lockedProject = params.get("lock_project") === "1";
  const preProjectId = params.get("project_id");
  const preProjectCode = params.get("project_code") || "";

  const searchInput = $("projectSearch");
  if (!searchInput) return;

  if (lockedProject) {
    searchInput.value = preProjectCode;
    searchInput.disabled = true;
  }

  const initial = await searchProjects(preProjectCode || "a");
  renderProjectOptions(initial);

  if (preProjectId && $("projectSelect")) {
    $("projectSelect").value = String(preProjectId);
  }

  if (lockedProject && $("projectSelect")) {
    $("projectSelect").disabled = true;
  }

  let timer = null;
  searchInput.addEventListener("input", () => {
    if (lockedProject) return;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const rows = await searchProjects(searchInput.value || "");
      renderProjectOptions(rows);
    }, 250);
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  newTaskModal = new bootstrap.Modal($("newTaskModal"));
  await setupProjectPicker();
  setModalDefaults();
  await loadTasks();

  $("goBackButton")?.addEventListener("click", goBack);
  $("showClosed")?.addEventListener("change", loadTasks);
  $("listStatusFilter")?.addEventListener("change", loadTasks);
  $("listProjectFilter")?.addEventListener("input", () => {
    clearTimeout(window.__taskFilterTimer);
    window.__taskFilterTimer = setTimeout(loadTasks, 250);
  });
  $("saveTask")?.addEventListener("click", submitTask);
  $("openNewTaskModal")?.addEventListener("click", () => {
    setModalDefaults();
    newTaskModal.show();
  });

  const params = new URLSearchParams(window.location.search);
  if (params.get("new") === "1") {
    setModalDefaults();
    newTaskModal.show();
  }
});
