const API = "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);

function showResult(obj) {
  $("resultCard").classList.remove("d-none");
  $("result").textContent = JSON.stringify(obj, null, 2);
}

function clearForm() {
  $("importForm").reset();
  $("sheet").value = "Hoja1";
  $("import_type").value = "OTS";
  $("importTypeHint").textContent = "Importando tipo OTS.";
  $("mapping_version").value = "v1";
  $("resultCard").classList.add("d-none");
  $("result").textContent = "";
}

document.addEventListener("DOMContentLoaded", () => {
  // Pre-rellenar año/semana con valores actuales del PC
  const now = new Date();
  const year = now.getFullYear();
  // Semana ISO aproximada (suficiente para MVP; si quieres, la calculamos exacta)
  const onejan = new Date(now.getFullYear(), 0, 1);
  const week = Math.ceil((((now - onejan) / 86400000) + onejan.getDay() + 1) / 7);

  $("snapshot_year").value = year;
  $("snapshot_week").value = Math.min(Math.max(week, 1), 53);

  $("btnClear").addEventListener("click", clearForm);

  $("import_type").addEventListener("change", (e) => {
    const selected = (e.target.value || "OTS").toUpperCase();
    $("importTypeHint").textContent = `Importando tipo ${selected}.`;
  });

  $("importForm").addEventListener("submit", async (e) => {
    e.preventDefault();

    const fileInput = $("file");
    if (!fileInput.files || fileInput.files.length === 0) {
      alert("Selecciona un archivo Excel.");
      return;
    }

    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    fd.append("snapshot_year", $("snapshot_year").value);
    fd.append("snapshot_week", $("snapshot_week").value);
    fd.append("sheet", $("sheet").value || "");
    fd.append("mapping_version", $("mapping_version").value || "");
    fd.append("import_type", $("import_type").value || "OTS");

    $("btnImport").disabled = true;
    $("btnImport").innerText = "Importando...";

    try {
      const res = await fetch(`${API}/imports`, {
        method: "POST",
        body: fd
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        showResult({ error: `HTTP ${res.status}`, detail: data });
        return;
      }

      showResult(data);
    } catch (err) {
      showResult({ error: "Network/JS error", detail: String(err) });
    } finally {
      $("btnImport").disabled = false;
      $("btnImport").innerHTML = '<i class="bi bi-upload me-1"></i>Importar';
    }
  });
});
