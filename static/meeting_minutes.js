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
    topicsBlocksTitle: "Temas tratados",
    addTopicBlock: "Añadir tema",
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
    topicsBlocksTitle: "Topics discussed",
    addTopicBlock: "Add topic",
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
    topic_blocks: getTopicBlocks(),
    topics: "",
    discussion: "",
    decisions_actions: "",
    planning_next_steps: "",
  };
}

function getTopicBlocks() {
  return Array.from(document.querySelectorAll(".topic-block")).map((row) => ({
    topic: row.querySelector(".topic-title").value,
    discussion: row.querySelector(".topic-discussion").value,
    decisions_actions: row.querySelector(".topic-decisions").value,
    planning_next_steps: row.querySelector(".topic-planning").value,
  }));
}

function fillFormForEdit(existing) {
  if (!existing) return;
  $("language").value = existing.language || "es";
  $("project_id").value = existing.project_id ? String(existing.project_id) : "";
  $("title").value = existing.title || "";
  $("project_subject").value = existing.project_subject || "";
  $("albaran_number").value = existing.albaran_number || "";
  $("meeting_date").value = existing.meeting_date || "";
  $("start_time").value = existing.start_time || "";
  $("end_time").value = existing.end_time || "";
  $("location").value = existing.location || "";
  $("phase").value = existing.phase || "";
  $("topicBlocksContainer").innerHTML = "";
  const topicBlocks = Array.isArray(existing.topic_blocks) ? existing.topic_blocks : [];
  if (!topicBlocks.length) addTopicBlockRow();
  topicBlocks.forEach((item) => addTopicBlockRow(item || {}));

  $("participantsContainer").innerHTML = "";
  const participants = Array.isArray(existing.participants) ? existing.participants : [];
  if (!participants.length) addParticipantRow();
  participants.forEach((item) => addParticipantRow(item || {}));
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

function addTopicBlockRow(initialData = {}) {
  const row = document.createElement("div");
  row.className = "topic-block border rounded p-3 mb-2";
  row.innerHTML = `
    <div class="mb-2"><label class="form-label">Temas tratados</label><textarea class="form-control topic-title" rows="2">${initialData.topic || ""}</textarea></div>
    <div class="mb-2"><label class="form-label">Detalle de la discusión</label><textarea class="form-control topic-discussion" rows="3">${initialData.discussion || ""}</textarea></div>
    <div class="mb-2"><label class="form-label">Decisiones / Acciones</label><textarea class="form-control topic-decisions" rows="2">${initialData.decisions_actions || ""}</textarea></div>
    <div class="mb-2"><label class="form-label">Planificación / Próximos pasos</label><textarea class="form-control topic-planning" rows="2">${initialData.planning_next_steps || ""}</textarea></div>
    <div class="text-end"><button type="button" class="btn btn-sm btn-outline-danger topic-remove">Eliminar tema</button></div>
  `;
  row.querySelector(".topic-remove").addEventListener("click", () => row.remove());
  $("topicBlocksContainer").appendChild(row);
}
window.addTopicBlockRow = addTopicBlockRow;

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
  const existing = window.__MEETING_MINUTES_EXISTING__;
  const isEdit = Boolean(existing && existing.id);
  const url = isEdit ? `/meeting-minutes/${encodeURIComponent(String(existing.id))}` : "/meeting-minutes/";
  const res = await fetch(url, {
    method: isEdit ? "PUT" : "POST",
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
  addTopicBlockRow();
  fillFormForEdit(window.__MEETING_MINUTES_EXISTING__);
  $("addParticipant").addEventListener("click", () => addParticipantRow());
  $("addTopicBlock").addEventListener("click", (event) => {
    event.preventDefault();
    addTopicBlockRow();
  });
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
