const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);
let templateItems = [];

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  }[char]));
}

function fillDatalist(id, values) {
  const list = $(id);
  if (!list) return;
  list.innerHTML = [...new Set(values.filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "es"))
    .map((value) => `<option value="${esc(value)}"></option>`)
    .join("");
}

function refreshOptions() {
  fillDatalist("phaseOptions", templateItems.map((item) => item.phase));
  fillDatalist("roleOptions", templateItems.map((item) => item.role));
}

function renderTemplate() {
  const body = $("templateBody");
  body.innerHTML = "";
  let currentPhase = "";
  for (const item of templateItems) {
    if (item.phase !== currentPhase) {
      currentPhase = item.phase;
      const phaseRow = document.createElement("tr");
      phaseRow.className = "table-primary";
      phaseRow.innerHTML = `<th colspan="5">${esc(currentPhase)}</th>`;
      body.appendChild(phaseRow);
    }

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input list="phaseOptions" class="form-control form-control-sm" value="${esc(item.phase)}"></td>
      <td><input list="roleOptions" class="form-control form-control-sm" value="${esc(item.role)}"></td>
      <td><input class="form-control form-control-sm" value="${esc(item.warehouse_type)}"></td>
      <td><textarea class="form-control form-control-sm" rows="2">${esc(item.task)}</textarea></td>
      <td class="text-nowrap">
        <button class="btn btn-sm btn-outline-primary me-1">Guardar</button>
        <button class="btn btn-sm btn-outline-danger">Eliminar</button>
      </td>`;
    const inputs = tr.querySelectorAll("input, textarea");
    tr.querySelector(".btn-outline-primary").addEventListener("click", async () => {
      await request(`${API}/api/checklist-template/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phase: inputs[0].value.trim(),
          role: inputs[1].value.trim(),
          warehouse_type: inputs[2].value.trim(),
          task: inputs[3].value.trim(),
        }),
      });
      await load();
    });
    tr.querySelector(".btn-outline-danger").addEventListener("click", async () => {
      if (confirm("¿Eliminar de la plantilla global?")) {
        await request(`${API}/api/checklist-template/${item.id}`, { method: "DELETE" });
        await load();
      }
    });
    body.appendChild(tr);
  }
}

async function load() {
  const data = await request(`${API}/api/checklist-template`);
  templateItems = data.items || [];
  refreshOptions();
  renderTemplate();
}

async function addTemplateItem() {
  const payload = {
    phase: $("newPhase").value.trim(),
    role: $("newRole").value.trim(),
    warehouse_type: $("newWarehouse").value.trim(),
    task: $("newTask").value.trim(),
  };
  if (!payload.phase || !payload.role || !payload.warehouse_type || !payload.task) {
    alert("Completa todos los campos.");
    return;
  }
  await request(`${API}/api/checklist-template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  ["newPhase", "newRole", "newWarehouse", "newTask"].forEach((id) => { $(id).value = ""; });
  await load();
}

document.addEventListener("DOMContentLoaded", () => {
  $("addTemplate").addEventListener("click", addTemplateItem);
  load().catch((err) => alert(err.message));
});
