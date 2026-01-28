import os
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import psycopg

from importer import read_and_normalize_excel, map_row, upsert_project, upsert_snapshot, compute_deltas

app = FastAPI()

# Static + templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# DB
DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")


# ---------- WEB ----------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/estado-proyecto", response_class=HTMLResponse)
def estado_proyecto(request: Request):
    return templates.TemplateResponse("project.html", {"request": request})

@app.get("/importacion", response_class=HTMLResponse)
def importacion(request: Request):
    return templates.TemplateResponse("import.html", {"request": request})


# ---------- API: Import ----------
@app.post("/imports")
async def import_excel(
    file: UploadFile = File(...),
    snapshot_year: int = Form(...),
    snapshot_week: int = Form(...),
    sheet: str = Form(""),
    mapping_version: str = Form(""),
):
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be .xlsx or .xls")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)

    df = read_and_normalize_excel(tmp_path, sheet)

    print("DEBUG df.shape:", df.shape)
    print("DEBUG df.columns (first 40):", list(df.columns)[:40])

    # ver una muestra de la primera fila
    first = df.iloc[0].to_dict() if len(df) else {}
    print("DEBUG first row keys (first 40):", list(first.keys())[:40])
    print("DEBUG first row sample:", {k: first[k] for k in list(first.keys())[:10]})


    imported = 0
    skipped = 0

    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO import_file (filename, snapshot_year, snapshot_week, mapping_version)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (file.filename, snapshot_year, snapshot_week, mapping_version),
            )
            import_file_id = cur.fetchone()[0]

            for _, row in df.iterrows():
                project_fields, snapshot_fields = map_row(row)

                code = (project_fields.get("project_code") or "").strip()
                name = project_fields.get("project_name")

                # Si viene vacío, ponemos un placeholder
                if (name is None) or (str(name).strip().lower() in ("", "nan", "none")):
                    project_fields["project_name"] = f"(SIN NOMBRE) {code}"

                if not code:
                    skipped += 1
                    continue

                pid = upsert_project(cur, project_fields)
                
                # ✅ calcular deltas SIEMPRE#

                snapshot_fields = compute_deltas(cur, pid, snapshot_year, snapshot_week, snapshot_fields)

                # ✅ UPSERT snapshot

                upsert_snapshot(cur, pid, import_file_id, snapshot_year, snapshot_week, snapshot_fields)
                imported += 1

        conn.commit()

    return {"status": "ok", "imported_rows": imported, "skipped_rows": skipped, "sheet": sheet}


# ---------- API: Search (opcional, por si luego quieres autocompletar) ----------
@app.get("/projects/search")
def search_projects(q: str = Query(..., min_length=1), limit: int = 20):
    q_like = f"%{q}%"
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_code, project_name, client, team, status
                FROM projects
                WHERE project_code ILIKE %s
                   OR project_name ILIKE %s
                   OR COALESCE(client,'') ILIKE %s
                ORDER BY project_code
                LIMIT %s
                """,
                (q_like, q_like, q_like, limit),
            )
            rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "project_code": r[1],
            "project_name": r[2],
            "client": r[3],
            "team": r[4],
            "status": r[5],
        }
        for r in rows
    ]


# ---------- API: Project state ----------
@app.get("/projects/{project_code}/state")
def project_state(project_code: str, weeks_back: int = 20):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_code, project_name, client, company, team, project_manager, consultant, status
                FROM projects
                WHERE project_code = %s
                """,
                (project_code,),
            )
            p = cur.fetchone()
            if not p:
                raise HTTPException(status_code=404, detail="Project not found")

            project_id = p[0]

            cur.execute(
                """
                SELECT *
                FROM project_snapshot
                WHERE project_id = %s
                ORDER BY snapshot_year DESC, snapshot_week DESC, snapshot_at DESC
                LIMIT 1
                """,
                (project_id,),
            )
            latest = cur.fetchone()
            if not latest:
                raise HTTPException(status_code=404, detail="No snapshots for project")

            colnames = [desc[0] for desc in cur.description]
            latest_dict = dict(zip(colnames, latest))

            cur.execute(
                """
                SELECT snapshot_year, snapshot_week, snapshot_at,
                       progress_c, deviation_cd, payment_pending,
                       dist_c, dist_pm, dist_e
                FROM project_snapshot
                WHERE project_id = %s
                ORDER BY snapshot_year DESC, snapshot_week DESC, snapshot_at DESC
                LIMIT %s
                """,
                (project_id, weeks_back),
            )
            series_rows = cur.fetchall()

    series = [
        {
            "year": r[0],
            "week": r[1],
            "snapshot_at": r[2].isoformat() if r[2] else None,
            "progress_c": float(r[3]) if r[3] is not None else None,
            "deviation_cd": float(r[4]) if r[4] is not None else None,
            "payment_pending": float(r[5]) if r[5] is not None else None,
            "dist_c": float(r[6]) if r[6] is not None else None,
            "dist_pm": float(r[7]) if r[7] is not None else None,
            "dist_e": float(r[8]) if r[8] is not None else None,
        }
        for r in series_rows
    ]
    series = list(reversed(series))

    project = {
        "id": p[0],
        "project_code": p[1],
        "project_name": p[2],
        "client": p[3],
        "company": p[4],
        "team": p[5],
        "project_manager": p[6],
        "consultant": p[7],
        "status": p[8],
    }

    return {"project": project, "latest": latest_dict, "series": series}
