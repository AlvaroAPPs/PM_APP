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
    status.textContent = value === null ? "Corrección eliminada, usando horas totales." : "Corrección guardada.";
  } catch (err) {
    status.textContent = "Error al guardar: " + err.message;
    status.classList.add("text-danger");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("tr[data-project-code]").forEach(row => {
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
  });
});
