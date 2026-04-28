const I18N = {
  es: {
    pageTitle: "Acta de Reunión",
    labelLanguage: "Idioma",
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
    btnExport: "Generar DOCX"
  },
  en: {
    pageTitle: "Meeting Minutes",
    labelLanguage: "Language",
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
    btnExport: "Export DOCX"
  }
};

function $(id) {
  return document.getElementById(id);
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

function renderParticipants() {
  const lang = $("language").value;
  const t = I18N[lang] || I18N.es;
  const container = $("participantsContainer");
  const rows = Array.from(container.querySelectorAll(".participant-row"));
  rows.forEach((row) => {
    row.querySelector(".participant-name").placeholder = t.name;
    row.querySelector(".participant-department").placeholder = t.department;
    row.querySelector(".participant-notes").placeholder = t.notes;
    row.querySelector(".participant-absent-label").textContent = t.absent;
    row.querySelector(".participant-remove").textContent = t.remove;
  });
}

function addParticipantRow(initialData = {}) {
  const container = $("participantsContainer");
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
  row.querySelector(".participant-remove").addEventListener("click", () => {
    row.remove();
  });
  container.appendChild(row);
  renderParticipants();
}

async function exportDocx(event) {
  event.preventDefault();
  const payload = {
    language: $("language").value,
    project_subject: $("project_subject").value,
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
  $("meetingMinutesForm").addEventListener("submit", exportDocx);
  applyLanguage($("language").value);
});
