const I18N = {
  es: {
    pageTitle: "Acta de Reunión",
    labelLanguage: "Idioma",
    labelProjectLink: "Proyecto",
    labelAlbaran: "Albarán",
    labelLookup: "Resultados albarán",
    labelTitle: "Título del acta",
    labelProject: "Proyecto / Asunto",
    labelDate: "Fecha",
    labelStart: "Hora inicio",
    labelEnd: "Hora fin",
    labelLocation: "Ubicación",
    labelPhase: "Fase",
    participantsTitle: "Participantes",
    addParticipant: "Añadir participante",
    name: "Nombre",
    department: "Departamento",
    absent: "Ausente",
    notes: "Notas",
    remove: "Eliminar",
    labelTopics: "Temas tratados",
    labelDiscussion: "Detalle de la discusión",
    labelDecisions: "Decisiones / Acciones",
    labelPlanning: "Planificación / Próximos pasos",
    btnExport: "Generar DOCX",
    btnSave: "Guardar acta",
    viewSavedBtn: "Ver actas guardadas",
    saveOk: "Acta guardada correctamente",
    saveError: "No se pudo guardar el acta",
    lookupAlbaran: "Albarán:",
  },
  en: {
    pageTitle: "Meeting Minutes",
    labelLanguage: "Language",
    labelProjectLink: "Project",
    labelAlbaran: "Delivery note",
    labelLookup: "Delivery note results",
    labelTitle: "Minutes title",
    labelProject: "Project / Subject",
    labelDate: "Meeting date",
    labelStart: "Start time",
    labelEnd: "End time",
    labelLocation: "Location",
    labelPhase: "Phase",
    participantsTitle: "Participants",
    addParticipant: "Add participant",
    name: "Name",
    department: "Department",
    absent: "Absent",
    notes: "Notes",
    remove: "Remove",
    labelTopics: "Topics discussed",
    labelDiscussion: "Detailed content",
    labelDecisions: "Decisions / Actions",
    labelPlanning: "Planning / Next steps",
    btnExport: "Export DOCX",
    btnSave: "Save minutes",
    viewSavedBtn: "View saved minutes",
    saveOk: "Minutes saved",
    saveError: "Could not save minutes",
    lookupAlbaran: "Delivery note:",
  }
};

function $(id) { return document.getElementById(id); }
function currentLang() { return $("language")?.value || "es"; }

function applyLanguage(lang) {
  const t = I18N[lang] || I18N.es;
  Object.keys(t).forEach((key) => {
    const el = $(key);
    if (el) el.textContent = t[key];
  });
  renderParticipants();
}

function getParticipants() {
  return Array.from(document.querySelectorAll(".participant-row")).map((row) => ({
    name: row.querySelector(".participant-name").value,
    department: row.querySelector(".participant-department").value,
    absent: row.querySelector(".participant-absent").checked,
    notes: row.querySelector(".participant-notes").value,
  }));
}

function collectPayload() {
  return {
    language: currentLang(),
    project_id: $("project_id").value ? Number($("project_id").value) : null,
    title: $("title").value,
    project_subject: $("project_subject").value,
    albaran_number: $("albaran_number").value,
    meeting_date: $("meeting_date").value,
    start_time: $("start_time").value,
    end_time: $("end_time").value,
    location: $("location").value,
    phase: $("phase").value,
    participants: getParticipants(),
    topics: $("topics").value,
    discussion: $("discussion").value,
    decisions_actions: $("decisions_actions").value,
    planning_next_steps: $("planning_next_steps").value,
  };
}

function updateSavedMinutesLink() {
  const link = $("viewSavedBtn");
  if (!link) return;
  const projectId = $("project_id")?.value;
  link.href = projectId ? `/meeting-minutes/list?project_id=${encodeURIComponent(projectId)}` : "/meeting-minutes/list";
}

function renderParticipants() {
  const t = I18N[currentLang()] || I18N.es;
  Array.from(document.querySelectorAll(".participant-row")).forEach((row) => {
    row.querySelector(".participant-name").placeholder = t.name;
    row.querySelector(".participant-department").placeholder = t.department;
    row.querySelector(".participant-notes").placeholder = t.notes;
    row.querySelector(".participant-absent-label").textContent = t.absent;
    row.querySelector(".participant-remove").textContent = t.remove;
  });
}

function addParticipantRow(initialData = {}) {
  const row = document.createElement("div");
  row.className = "participant-row border rounded p-2 mb-2";
  row.innerHTML = `
    <div class="row g-2 align-items-center">
      <div class="col-md-3"><input class="form-control participant-name" type="text" value="${initialData.name || ""}" /></div>
      <div class="col-md-3"><input class="form-control participant-department" type="text" value="${initialData.department || ""}" /></div>
      <div class="col-md-2"><div class="form-check"><input class="form-check-input participant-absent" type="checkbox" ${initialData.absent ? "checked" : ""} /><label class="form-check-label participant-absent-label">Ausente</label></div></div>
      <div class="col-md-3"><input class="form-control participant-notes" type="text" value="${initialData.notes || ""}" /></div>
      <div class="col-md-1"><button type="button" class="btn btn-sm btn-outline-danger participant-remove">Eliminar</button></div>
    </div>`;
  row.querySelector(".participant-remove").addEventListener("click", () => row.remove());
  $("participantsContainer").appendChild(row);
  renderParticipants();
}

async function searchProjects(query) {
  if (!query || query.trim().length < 1) return [];
  const res = await fetch(`/projects/search?q=${encodeURIComponent(query.trim())}`);
  if (!res.ok) return [];
  return res.json();
}

function renderProjectOptions(options) {
  const select = $("project_id");
  const current = select.value;
  select.innerHTML = '<option value="">Sin asociar</option>';
  for (const p of options) {
    const opt = document.createElement("option");
    opt.value = String(p.id);
    opt.textContent = `${p.project_code} - ${p.project_name}`;
    select.appendChild(opt);
  }
  if (current && Array.from(select.options).some((opt) => opt.value === current)) {
    select.value = current;
  }
  updateSavedMinutesLink();
}

async function searchAlbaranes(query) {
  const res = await fetch(`/meeting-minutes/albaranes/search?q=${encodeURIComponent(query || "")}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.items || [];
}

function renderAlbaranResults(items) {
  const select = $("albaran_results");
  const t = I18N[currentLang()] || I18N.es;
  select.innerHTML = "";
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item;
    opt.textContent = `${t.lookupAlbaran} ${item}`;
    select.appendChild(opt);
  }
}

async function saveMinutes() {
  const t = I18N[currentLang()] || I18N.es;
  const payload = collectPayload();
  const res = await fetch("/meeting-minutes/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : "";
    } catch (_err) {}
    alert(`${t.saveError}${detail}`);
    return;
  }
  alert(t.saveOk);
}

async function exportDocx(event) {
  event.preventDefault();
  const payload = collectPayload();
  const res = await fetch("/meeting-minutes/export.docx/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert("Error generating DOCX");
    return;
  }
  const blob = await res.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "meeting_minutes.docx";
  link.click();
  URL.revokeObjectURL(link.href);
}

document.addEventListener("DOMContentLoaded", () => {
  addParticipantRow();
  $("addParticipant").addEventListener("click", () => addParticipantRow());
  $("language").addEventListener("change", () => {
    applyLanguage(currentLang());
    searchAlbaranes($("albaran_search").value || "").then(renderAlbaranResults);
  });
  $("project_id").addEventListener("change", updateSavedMinutesLink);
  $("project_search").addEventListener("input", async (event) => {
    const options = await searchProjects(event.target.value || "");
    renderProjectOptions(options);
  });
  $("albaran_search").addEventListener("input", async (event) => {
    const items = await searchAlbaranes(event.target.value || "");
    renderAlbaranResults(items);
  });
  $("albaran_results").addEventListener("change", (event) => {
    if (event.target.value) $("albaran_number").value = event.target.value;
  });
  $("btnSave").addEventListener("click", saveMinutes);
  $("meetingMinutesForm").addEventListener("submit", exportDocx);
  applyLanguage(currentLang());
  updateSavedMinutesLink();
  searchAlbaranes("").then(renderAlbaranResults);
});
