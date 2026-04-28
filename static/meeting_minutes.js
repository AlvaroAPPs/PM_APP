const I18N = {
  es: {
    pageTitle: "Acta de Reunión",
    labelLanguage: "Idioma",
    labelProjectLink: "Proyecto",
    labelAlbaran: "Albarán",
    labelLookup: "Buscar proyecto / albarán",
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
    lookupProject: "Proyecto:",
    lookupAlbaran: "Albarán:",
  },
  en: {
    pageTitle: "Meeting Minutes",
    labelLanguage: "Language",
    labelProjectLink: "Project",
    labelAlbaran: "Delivery note",
    labelLookup: "Search project / delivery note",
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
    lookupProject: "Project:",
    lookupAlbaran: "Delivery note:",
  }
};

function $(id) { return document.getElementById(id); }

function currentLang() {
  return $("language")?.value || "es";
}

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
  const rows = Array.from(document.querySelectorAll(".participant-row"));
  rows.forEach((row) => {
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
    </div>
  `;
  row.querySelector(".participant-remove").addEventListener("click", () => row.remove());
  $("participantsContainer").appendChild(row);
  renderParticipants();
}

async function lookupProjectOrAlbaran() {
  const query = $("lookup_query")?.value || "";
  const res = await fetch(`/meeting-minutes/lookups?q=${encodeURIComponent(query)}`);
  if (!res.ok) return;
  const data = await res.json();
  const t = I18N[currentLang()] || I18N.es;

  const projectContainer = $("lookup_project_results");
  projectContainer.innerHTML = "";
  data.projects.forEach((project) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm btn-outline-primary";
    btn.textContent = `${t.lookupProject} ${project.project_code} - ${project.project_name}`;
    btn.addEventListener("click", () => {
      $("project_id").value = String(project.id);
      updateSavedMinutesLink();
    });
    projectContainer.appendChild(btn);
  });

  const albaranContainer = $("lookup_albaran_results");
  albaranContainer.innerHTML = "";
  data.albaranes.forEach((albaran) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm btn-outline-secondary";
    btn.textContent = `${t.lookupAlbaran} ${albaran}`;
    btn.addEventListener("click", () => {
      $("albaran_number").value = albaran;
    });
    albaranContainer.appendChild(btn);
  });
}

async function saveMinutes() {
  const t = I18N[currentLang()] || I18N.es;
  const payload = collectPayload();
  const res = await fetch("/meeting-minutes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = data.detail ? `: ${data.detail}` : "";
    } catch (_err) {
      detail = "";
    }
    alert(`${t.saveError}${detail}`);
    return;
  }
  alert(t.saveOk);
}

async function exportDocx(event) {
  event.preventDefault();
  const payload = collectPayload();
  const res = await fetch("/meeting-minutes/export.docx", {
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
  $("language").addEventListener("change", (e) => applyLanguage(e.target.value));
  $("project_id").addEventListener("change", updateSavedMinutesLink);
  $("lookup_btn").addEventListener("click", lookupProjectOrAlbaran);
  $("lookup_query").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      lookupProjectOrAlbaran();
    }
  });
  $("btnSave").addEventListener("click", saveMinutes);
  $("meetingMinutesForm").addEventListener("submit", exportDocx);
  applyLanguage(currentLang());
  updateSavedMinutesLink();
  lookupProjectOrAlbaran();
});
