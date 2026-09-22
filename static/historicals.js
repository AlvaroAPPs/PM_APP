const API = "http://127.0.0.1:8000";

async function saveClosedHours(row, value) {
  const projectCode = row.dataset.projectCode;
  const status = row.querySelector(".closed-hours-status");
  status.textContent = "Guardando...";
  status.classList.remove("text-danger");
  try {
    const res = await fetch(`${API}/historicals/${encodeURIComponent(projectCode)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ closed_hours_override: value }),
    });
    if (!res.ok) throw new Error(await res.text());
    status.textContent = value === null ? "Corrección eliminada, usando horas congeladas." : "Corrección guardada.";
  } catch (err) {
    status.textContent = "Error al guardar: " + err.message;
    status.classList.add("text-danger");
  }
}

async function sendReview(row, request, statusSelector = ".review-status") {
  const status = row.querySelector(statusSelector);
  status.textContent = "Guardando...";
  status.classList.remove("text-danger");
  try {
    const res = await fetch(request.url, {
      method: request.method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request.body),
    });
    if (!res.ok) throw new Error(await res.text());
    window.location.reload();
  } catch (err) {
    status.textContent = "Error al guardar: " + err.message;
    status.classList.add("text-danger");
  }
}

function setupVanishedRow(row) {
  const code = encodeURIComponent(row.dataset.projectCode);

  row.querySelector(".vanished-keep").addEventListener("click", () => {
    sendReview(
      row,
      { url: `${API}/historicals/${code}/vanished-review`, method: "POST", body: { action: "keep" } },
      ".vanished-status",
    );
  });

  row.querySelector(".vanished-exclude").addEventListener("click", () => {
    sendReview(
      row,
      { url: `${API}/historicals/${code}/vanished-review`, method: "POST", body: { action: "exclude" } },
      ".vanished-status",
    );
  });
}

function setupReviewRow(row) {
  const code = encodeURIComponent(row.dataset.projectCode);
  const sourceHours = Number(row.dataset.sourceHours);

  row.querySelector(".review-keep").addEventListener("click", () => {
    sendReview(row, {
      url: `${API}/historicals/${code}/hours-review`,
      method: "POST",
      body: { action: "keep", source_hours: sourceHours },
    });
  });

  row.querySelector(".review-accept").addEventListener("click", () => {
    sendReview(row, {
      url: `${API}/historicals/${code}/hours-review`,
      method: "POST",
      body: { action: "accept", source_hours: sourceHours },
    });
  });

  row.querySelector(".review-manual").addEventListener("click", () => {
    const raw = window.prompt("Horas de cierre a usar en el informe para este proyecto:");
    if (raw === null) return;
    const value = Number(raw.replace(",", "."));
    if (raw.trim() === "" || Number.isNaN(value) || value < 0) {
      const status = row.querySelector(".review-status");
      status.textContent = "Introduce un número válido (>= 0).";
      status.classList.add("text-danger");
      return;
    }
    sendReview(row, {
      url: `${API}/historicals/${code}`,
      method: "PATCH",
      body: { closed_hours_override: value },
    });
  });
}

function setupOverrideRow(row) {
  const input = row.querySelector(".closed-hours-input");
  const saveBtn = row.querySelector(".closed-hours-save");
  const clearBtn = row.querySelector(".closed-hours-clear");

  saveBtn.addEventListener("click", () => {
    const raw = input.value.trim();
    if (raw === "") {
      saveClosedHours(row, null);
      return;
    }
    const num = Number(raw);
    if (Number.isNaN(num) || num < 0) {
      const status = row.querySelector(".closed-hours-status");
      status.textContent = "Introduce un número válido (>= 0).";
      status.classList.add("text-danger");
      return;
    }
    saveClosedHours(row, num);
  });

  clearBtn.addEventListener("click", () => {
    input.value = "";
    saveClosedHours(row, null);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("#reviewTable tr[data-project-code]").forEach(setupReviewRow);
  document.querySelectorAll("#vanishedTable tr[data-project-code]").forEach(setupVanishedRow);
  document.querySelectorAll("tr[data-project-code]").forEach(row => {
    if (row.querySelector(".closed-hours-input")) setupOverrideRow(row);
  });
});
