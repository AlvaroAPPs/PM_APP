const API = "http://127.0.0.1:8000";
const $ = id => document.getElementById(id);

let items = [];
let ganttInstance = null;
let currentViewMode = "Month";

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(await res.text());
  if (res.status === 204) return null;
  return res.json();
}

function toIsoDate(d) {
  const date = (d instanceof Date) ? d : new Date(d);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function orderItems(list) {
  const topLevel = list.filter(it => it.parent_id === null).sort((a, b) => a.position - b.position || a.id - b.id);
  const children = {};
  for (const it of list) {
    if (it.parent_id !== null) {
      (children[it.parent_id] = children[it.parent_id] || []).push(it);
    }
  }
  for (const key in children) children[key].sort((a, b) => a.position - b.position || a.id - b.id);

  const ordered = [];
  for (const parent of topLevel) {
    ordered.push(parent);
    for (const child of (children[parent.id] || [])) ordered.push(child);
  }
  return ordered;
}

function itemClass(item) {
  const classes = [];
  classes.push(item.source === "phase" ? "gantt-phase" : item.source === "checklist" ? "gantt-checklist" : "gantt-manual");
  if (item.is_milestone) classes.push("gantt-milestone");
  return classes.join(" ");
}

function buildTasks(list) {
  return orderItems(list).map(item => ({
    id: String(item.id),
    name: (item.parent_id !== null ? "↳ " : "") + item.title,
    start: item.start_date,
    end: item.is_milestone ? item.start_date : item.end_date,
    progress: item.progress || 0,
    custom_class: itemClass(item),
  }));
}

function renderGantt() {
  const container = $("gantt");
  container.innerHTML = "";
  if (items.length === 0) {
    container.innerHTML = '<div class="gantt-empty">Este proyecto todavía no tiene tareas en el planning.</div>';
    ganttInstance = null;
    return;
  }
  const tasks = buildTasks(items);
  ganttInstance = new Gantt("#gantt", tasks, {
    view_mode: currentViewMode,
    language: "es",
    on_click: task => openModalForEdit(task.id),
    on_date_change: async (task, start, end) => {
      try {
        await request(`${API}/api/gantt-items/${task.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ start_date: toIsoDate(start), end_date: toIsoDate(end) }),
        });
        await load(false);
      } catch (err) {
        alert(err.message);
        await load(false);
      }
    },
    on_progress_change: async (task, progress) => {
      try {
        await request(`${API}/api/gantt-items/${task.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ progress: Math.round(progress) }),
        });
        await load(false);
      } catch (err) {
        alert(err.message);
        await load(false);
      }
    },
  });
}

function populateParentSelect(excludeId) {
  const select = $("taskParent");
  select.innerHTML = '<option value="">Ninguna (tarea de primer nivel)</option>';
  for (const item of items) {
    if (item.parent_id !== null) continue; // solo un nivel de subtareas
    if (excludeId !== null && item.id === excludeId) continue;
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.title;
    select.appendChild(opt);
  }
}

function setProgressField(value) {
  $("taskProgress").value = value;
  $("taskProgressValue").textContent = value;
}

function openModalForCreate() {
  populateParentSelect(null);
  $("taskId").value = "";
  $("taskTitle").value = "";
  const today = toIsoDate(new Date());
  $("taskStart").value = today;
  $("taskEnd").value = today;
  $("taskMilestone").checked = false;
  $("taskParent").value = "";
  setProgressField(0);
  $("taskModalTitle").textContent = "Añadir tarea / hito";
  $("taskDeleteBtn").classList.add("d-none");
  $("taskReorderBtns").classList.add("d-none");
  bootstrap.Modal.getOrCreateInstance($("taskModal")).show();
}

function openModalForEdit(itemId) {
  const item = items.find(it => String(it.id) === String(itemId));
  if (!item) return;
  populateParentSelect(item.id);
  $("taskId").value = item.id;
  $("taskTitle").value = item.title;
  $("taskStart").value = item.start_date;
  $("taskEnd").value = item.end_date;
  $("taskMilestone").checked = item.is_milestone;
  $("taskParent").value = item.parent_id ?? "";
  setProgressField(item.progress || 0);
  $("taskModalTitle").textContent = "Editar tarea";
  $("taskDeleteBtn").classList.remove("d-none");
  $("taskReorderBtns").classList.remove("d-none");
  bootstrap.Modal.getOrCreateInstance($("taskModal")).show();
}

async function moveTask(direction) {
  const id = Number($("taskId").value);
  const item = items.find(it => it.id === id);
  if (!item) return;
  const siblings = items
    .filter(it => it.parent_id === item.parent_id)
    .sort((a, b) => a.position - b.position || a.id - b.id);
  const idx = siblings.findIndex(it => it.id === id);
  const swapIdx = direction === "up" ? idx - 1 : idx + 1;
  if (swapIdx < 0 || swapIdx >= siblings.length) return;
  const other = siblings[swapIdx];
  try {
    await request(`${API}/api/gantt-items/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position: other.position }),
    });
    await request(`${API}/api/gantt-items/${other.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position: item.position }),
    });
    bootstrap.Modal.getInstance($("taskModal"))?.hide();
    await load(false);
  } catch (err) {
    alert(err.message);
  }
}

async function saveTask() {
  const title = $("taskTitle").value.trim();
  if (!title) { alert("El título es obligatorio."); return; }
  const isMilestone = $("taskMilestone").checked;
  const start = $("taskStart").value;
  const end = isMilestone ? start : ($("taskEnd").value || start);
  if (!start) { alert("La fecha de inicio es obligatoria."); return; }
  if (end < start) { alert("La fecha de fin no puede ser anterior a la de inicio."); return; }

  const id = $("taskId").value;
  const parentValue = $("taskParent").value;
  const payload = {
    title,
    start_date: start,
    end_date: end,
    is_milestone: isMilestone,
    parent_id: parentValue ? Number(parentValue) : null,
    progress: Number($("taskProgress").value) || 0,
  };

  try {
    if (id) {
      await request(`${API}/api/gantt-items/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      await request(`${API}/api/projects/${encodeURIComponent(window.PROJECT_CODE)}/gantt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    bootstrap.Modal.getInstance($("taskModal"))?.hide();
    await load(false);
  } catch (err) {
    alert(err.message);
  }
}

async function deleteTask() {
  const id = $("taskId").value;
  if (!id) return;
  if (!confirm("¿Eliminar esta tarea del planning? Si tiene subtareas, también se eliminarán.")) return;
  try {
    await request(`${API}/api/gantt-items/${id}`, { method: "DELETE" });
    bootstrap.Modal.getInstance($("taskModal"))?.hide();
    await load(false);
  } catch (err) {
    alert(err.message);
  }
}

async function load(showErrors = true) {
  try {
    const data = await request(`${API}/api/projects/${encodeURIComponent(window.PROJECT_CODE)}/gantt`);
    items = data.items;
    $("projectName").textContent = data.project.project_name ? `· ${data.project.project_name}` : "";
    const badge = $("projectProgressBadge");
    if (data.project.progress_w !== null && data.project.progress_w !== undefined) {
      badge.textContent = `Avance del proyecto: ${data.project.progress_w}%`;
      badge.classList.remove("d-none");
    } else {
      badge.classList.add("d-none");
    }
    renderGantt();
  } catch (err) {
    if (showErrors) alert(err.message);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("printPdfLink").href = `/projects/${encodeURIComponent(window.PROJECT_CODE)}/planning/report.pdf`;
  $("addTaskBtn").addEventListener("click", openModalForCreate);
  $("taskSaveBtn").addEventListener("click", saveTask);
  $("taskDeleteBtn").addEventListener("click", deleteTask);
  $("taskMoveUpBtn").addEventListener("click", () => moveTask("up"));
  $("taskMoveDownBtn").addEventListener("click", () => moveTask("down"));
  $("taskMilestone").addEventListener("change", () => {
    $("taskEnd").disabled = $("taskMilestone").checked;
  });
  $("taskProgress").addEventListener("input", () => {
    $("taskProgressValue").textContent = $("taskProgress").value;
  });
  document.querySelectorAll(".view-mode-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view-mode-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentViewMode = btn.dataset.mode;
      if (ganttInstance) {
        ganttInstance.change_view_mode(currentViewMode);
      }
    });
  });
  load();
});
