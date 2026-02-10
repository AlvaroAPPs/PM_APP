const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

let projectOptions = [];
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

function getListFilters() {
  const params = new URLSearchParams(window.location.search);
  const projectId = Number(params.get("project_id") || 0);
  const type = (params.get("type") || "").trim().toUpperCase();
  return {
    projectId: Number.isFinite(projectId) && projectId > 0 ? projectId : null,
    type: type === "TASK" || type === "PP" ? type : null,
    projectCode: params.get("project_code") || "",
  };
}

function buildProjectDetailLink(projectCode) {
  const returnTo = `${window.location.pathname}${window.location.search}`;
  const params = new URLSearchParams();
  params.set("q", projectCode || "");
  params.set("return_to", returnTo);
  return `/estado-proyecto?${params.toString()}`;
}

async function searchProjects(query) {
  if (!query || query.trim().length < 1) return [];
  const res = await fetch(`${API}/projects/search?q=${encodeURIComponent(query.trim())}`);
  if (!res.ok) return [];
  return res.json();
}

function renderProjectOptions(options) {
  projectOptions = options;
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

function resetTaskForm() {
  editingTaskId = null;
  $("taskModalTitle").textContent = "Nueva Tarea / PP";
  $("saveTask").textContent = "Guardar";
  $("taskFormError").textContent = "";
  $("taskType").value = "TASK";
  $("ownerRole").value = "PM";
  $("plannedDate").value = "";
  $("taskStatus").value = "OPEN";
  $("taskDescription").value = "";
}

function fillTaskForm(task) {
  editingTaskId = task.id;
  $("taskModalTitle").textContent = "Editar Tarea / PP";
  $("saveTask").textContent = "Actualizar";
  $("taskType").value = task.type || "TASK";
  $("ownerRole").value = task.owner_role || "PM";
  $("plannedDate").value = task.planned_date || "";
  $("taskStatus").value = task.status || "OPEN";
  $("taskDescription").value = task.description || "";
  if ($("projectSelect")) {
    $("projectSelect").value = String(task.project_id);
  }
  $("taskFormError").textContent = "";
}

async function closeTask(taskId) {
  await fetch(`${API}/project-tasks/${taskId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "CLOSED" }),
  });
  loadTasks();
}

async function loadTasks() {
  const showClosed = $("showClosed")?.checked ? "true" : "false";
  const filters = getListFilters();
  const params = new URLSearchParams();
  params.set("include_closed", showClosed);
  if (filters.projectId) params.set("project_id", String(filters.projectId));
  if (filters.type) params.set("type", filters.type);

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
    tr.innerHTML = `
      <td><div>${row.project_name || "—"}</div><div class="text-muted small">${row.project_code || "—"}</div></td>
      <td>${typeLabel(row.type)}</td>
      <td>${row.owner_role}</td>
      <td>${fmtDate(row.planned_date)}</td>
      <td><span class="badge text-bg-light border">${statusLabel(row.status)}</span></td>
      <td>${row.description || ""}</td>
      <td class="text-end"></td>
    `;

    const actionsTd = tr.querySelector("td:last-child");

    const linkBtn = document.createElement("a");
    const projectCode = (row.project_code || filters.projectCode || "").trim();
    linkBtn.className = "btn btn-sm btn-outline-primary me-1";
    linkBtn.textContent = "Link";
    if (projectCode) {
      linkBtn.href = buildProjectDetailLink(projectCode);
    } else {
      linkBtn.href = "#";
      linkBtn.classList.add("disabled");
      linkBtn.setAttribute("aria-disabled", "true");
      linkBtn.title = "Sin código de proyecto";
    }
    actionsTd.appendChild(linkBtn);

    const editBtn = document.createElement("button");
    editBtn.className = "btn btn-sm btn-outline-secondary me-1";
    editBtn.textContent = "Editar";
    editBtn.addEventListener("click", () => {
      fillTaskForm(row);
      newTaskModal.show();
    });
    actionsTd.appendChild(editBtn);

    if (row.status === "CLOSED") {
      const reopen = document.createElement("button");
      reopen.className = "btn btn-sm btn-outline-primary";
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
    } else {
      const closeBtn = document.createElement("button");
      closeBtn.className = "btn btn-sm btn-outline-danger";
      closeBtn.textContent = "Cerrar";
      closeBtn.addEventListener("click", async () => closeTask(row.id));
      actionsTd.appendChild(closeBtn);
    }

    body.appendChild(tr);
  }
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

  const endpoint = editingTaskId ? `${API}/project-tasks/${editingTaskId}` : `${API}/project-tasks`;
  const method = editingTaskId ? "PUT" : "POST";
  const updatePayload = editingTaskId
    ? {
        type: payload.type,
        owner_role: payload.owner_role,
        planned_date: payload.planned_date,
        status: payload.status,
        description: payload.description,
      }
    : payload;

  const res = await fetch(endpoint, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updatePayload),
  });

  if (!res.ok) {
    $("taskFormError").textContent = editingTaskId
      ? "No se pudo actualizar la tarea."
      : "No se pudo guardar la tarea.";
    return;
  }

  resetTaskForm();
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

  const baseQuery = preProjectCode || "";
  const initial = await searchProjects(baseQuery || " ");
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
  await loadTasks();

  $("showClosed")?.addEventListener("change", loadTasks);
  $("saveTask")?.addEventListener("click", submitTask);
  $("openNewTaskModal")?.addEventListener("click", () => {
    resetTaskForm();
    newTaskModal.show();
  });
  $("newTaskModal")?.addEventListener("hidden.bs.modal", resetTaskForm);
  $("goBackBtn")?.addEventListener("click", () => window.history.back());

  const params = new URLSearchParams(window.location.search);
  if (params.get("new") === "1") {
    resetTaskForm();
    newTaskModal.show();
  }
});
