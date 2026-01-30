import os
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import psycopg

from importer import read_and_normalize_excel, map_row, upsert_project, upsert_snapshot, compute_deltas

app = FastAPI()

# Static + templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# DB
DB_DSN = os.environ.get("DB_DSN", "postgresql://postgres:TU_PASSWORD@localhost:5432/mecalux")

PHASES = ("design", "development", "pem", "hypercare")
ROLES = ("pm", "consultant", "technician")


class AssignedHoursPhaseIn(BaseModel):
    phase: str
    hours: float | None = None


class AssignedHoursRoleIn(BaseModel):
    role: str
    hours: float | None = None


class ProjectCommentIn(BaseModel):
    comment_text: str | None = None


def normalize_comment(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def ensure_details_columns(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        ALTER TABLE projects
        ADD COLUMN IF NOT EXISTS comments TEXT,
        ADD COLUMN IF NOT EXISTS hours_design NUMERIC DEFAULT 0,
        ADD COLUMN IF NOT EXISTS hours_development NUMERIC DEFAULT 0,
        ADD COLUMN IF NOT EXISTS hours_pem NUMERIC DEFAULT 0,
        ADD COLUMN IF NOT EXISTS hours_hypercare NUMERIC DEFAULT 0,
        ADD COLUMN IF NOT EXISTS hours_pm NUMERIC DEFAULT 0,
        ADD COLUMN IF NOT EXISTS hours_consultant NUMERIC DEFAULT 0,
        ADD COLUMN IF NOT EXISTS hours_technician NUMERIC DEFAULT 0;
        """
    )


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


# ---------- API: Project details ----------
@app.get("/projects/{project_code}/details")
def project_details(project_code: str):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_details_columns(cur)
            cur.execute(
                """
                SELECT id, project_code, project_name, client, company, team, project_manager, consultant, status,
                       comments,
                       hours_design, hours_development, hours_pem, hours_hypercare,
                       hours_pm, hours_consultant, hours_technician
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
                SELECT comments
                FROM project_snapshot
                WHERE project_id = %s
                  AND comments IS NOT NULL
                  AND comments <> ''
                ORDER BY snapshot_year DESC, snapshot_week DESC, snapshot_at DESC
                LIMIT 1
                """,
                (project_id,),
            )
            latest_comment_row = cur.fetchone()

    assigned_hours_phase = {
        "design": float(p[10] or 0),
        "development": float(p[11] or 0),
        "pem": float(p[12] or 0),
        "hypercare": float(p[13] or 0),
    }

    assigned_hours_role = {
        "pm": float(p[14] or 0),
        "consultant": float(p[15] or 0),
        "technician": float(p[16] or 0),
    }

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

    project_comment = p[9] if p[9] is not None else latest_dict.get("comments")
    excel_comments = latest_comment_row[0] if latest_comment_row else latest_dict.get("comments")
    return {
        "project": project,
        "latest": latest_dict,
        "assigned_hours_phase": assigned_hours_phase,
        "assigned_hours_role": assigned_hours_role,
        "project_comment": normalize_comment(project_comment),
        "excel_comments": normalize_comment(excel_comments),
    }


@app.post("/projects/{project_id}/assigned-hours/phase")
def update_assigned_hours_phase(project_id: int, payload: AssignedHoursPhaseIn):
    if payload.phase not in PHASES:
        raise HTTPException(status_code=400, detail="Invalid phase")
    hours = payload.hours if payload.hours is not None else 0
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_details_columns(cur)
            column_map = {
                "design": "hours_design",
                "development": "hours_development",
                "pem": "hours_pem",
                "hypercare": "hours_hypercare",
            }
            column = column_map[payload.phase]
            cur.execute(
                f"""
                UPDATE projects
                SET {column} = %s
                WHERE id = %s
                """,
                (hours, project_id),
            )
        conn.commit()
    return {"status": "ok"}


@app.post("/projects/{project_id}/assigned-hours/role")
def update_assigned_hours_role(project_id: int, payload: AssignedHoursRoleIn):
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    hours = payload.hours if payload.hours is not None else 0
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_details_columns(cur)
            column_map = {
                "pm": "hours_pm",
                "consultant": "hours_consultant",
                "technician": "hours_technician",
            }
            column = column_map[payload.role]
            cur.execute(
                f"""
                UPDATE projects
                SET {column} = %s
                WHERE id = %s
                """,
                (hours, project_id),
            )
        conn.commit()
    return {"status": "ok"}


@app.post("/projects/{project_id}/comments")
def update_project_comment(project_id: int, payload: ProjectCommentIn):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_details_columns(cur)
            cur.execute(
                """
                UPDATE projects
                SET comments = %s
                WHERE id = %s
                """,
                (payload.comment_text, project_id),
            )
        conn.commit()
    return {"status": "ok"}
