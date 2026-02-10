const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

let projectOptions = [];
let lockedProject = false;
let newTaskModal = null;

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

async function loadTasks() {
  const showClosed = $("showClosed")?.checked ? "true" : "false";
  const res = await fetch(`${API}/project-tasks?include_closed=${showClosed}`);
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

  const res = await fetch(`${API}/project-tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    $("taskFormError").textContent = "No se pudo guardar la tarea.";
    return;
  }

  $("taskFormError").textContent = "";
  $("taskDescription").value = "";
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
  $("openNewTaskModal")?.addEventListener("click", () => newTaskModal.show());

  const params = new URLSearchParams(window.location.search);
  if (params.get("new") === "1") {
    newTaskModal.show();
  }
});
