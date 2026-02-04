import io
import os
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import pandas as pd
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


def to_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def to_date_iso(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def fetch_deviations_results(
    equipo: str | None = None,
    order_phase: str | None = None,
) -> tuple[list[dict], list[str], set[str]]:
    sql = """
    WITH ranked AS (
        SELECT
            p.id AS project_id,
            p.project_code,
            p.project_name,
            s.team,
            s.order_phase,
            s.ordered_total,
            s.real_hours,
            s.desviacion_pct,
            s.comments,
            s.snapshot_year,
            s.snapshot_week,
            s.snapshot_at,
            ROW_NUMBER() OVER (
                PARTITION BY p.id
                ORDER BY s.snapshot_year DESC, s.snapshot_week DESC, s.snapshot_at DESC
            ) AS rn
        FROM projects p
        JOIN project_snapshot s ON s.project_id = p.id
        WHERE (%s::text IS NULL OR s.team = %s::text)
          AND (%s::text IS NULL OR s.order_phase = %s::text)
    )
    SELECT *
    FROM ranked
    WHERE rn <= 5
    """
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (equipo, equipo, order_phase, order_phase))
            rows = cur.fetchall()
            colnames = [desc[0] for desc in cur.description]

    grouped: dict[int, list[dict]] = {}
    for row in rows:
        record = dict(zip(colnames, row))
        grouped.setdefault(record["project_id"], []).append(record)

    columns = [
        "Proyecto",
        "Equipo",
        "Order phase",
        "Horas totales",
        "Horas reales",
        "Desviación",
        "Comentario",
    ]
    snapshot_columns = []
    for idx in range(1, 6):
        snapshot_columns.extend(
            [
                f"S{idx} horas totales",
                f"S{idx} horas reales",
                f"S{idx} desviación",
            ]
        )
    columns.extend(snapshot_columns)
    numeric_columns = set(columns) - {"Proyecto", "Equipo", "Order phase", "Comentario"}

    results = []
    for items in grouped.values():
        items_sorted = sorted(items, key=lambda item: item["rn"])
        latest = next((item for item in items_sorted if item["rn"] == 1), None)
        prev = next((item for item in items_sorted if item["rn"] == 2), None)
        if latest is None or prev is None:
            continue
        latest_dev = to_float(latest.get("desviacion_pct"))
        prev_dev = to_float(prev.get("desviacion_pct"))
        # A snapshot is deviated when desviacion_pct != 0.
        if not (latest_dev is not None and latest_dev != 0):
            continue
        if not (prev_dev is not None and prev_dev != 0):
            continue

        row = {
            "Proyecto": latest.get("project_name"),
            "Equipo": latest.get("team"),
            "Order phase": latest.get("order_phase"),
            "Horas totales": to_float(latest.get("ordered_total")),
            "Horas reales": to_float(latest.get("real_hours")),
            "Desviación": latest_dev,
            "Comentario": normalize_comment(latest.get("comments")),
        }

        snapshots_by_rn = {item["rn"]: item for item in items_sorted}
        for idx in range(1, 6):
            snapshot = snapshots_by_rn.get(idx)
            row[f"S{idx} horas totales"] = to_float(
                snapshot.get("ordered_total") if snapshot else None
            )
            row[f"S{idx} horas reales"] = to_float(
                snapshot.get("real_hours") if snapshot else None
            )
            row[f"S{idx} desviación"] = to_float(
                snapshot.get("desviacion_pct") if snapshot else None
            )
        results.append(row)

    results = sorted(results, key=lambda item: (item["Proyecto"] or "").lower())
    return results, columns, numeric_columns


def fetch_filter_options() -> tuple[list[str], list[str]]:
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT team
                FROM project_snapshot
                WHERE team IS NOT NULL AND team <> ''
                ORDER BY team
                """
            )
            teams = [row[0] for row in cur.fetchall()]
            cur.execute(
                """
                SELECT DISTINCT order_phase
                FROM project_snapshot
                WHERE order_phase IS NOT NULL AND order_phase <> ''
                ORDER BY order_phase
                """
            )
            phases = [row[0] for row in cur.fetchall()]
    return teams, phases


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

PHASES_INFO = (
    ("date_kickoff", "Kick-off"),
    ("date_design", "Design"),
    ("date_validation", "Validation"),
    ("date_golive", "Go-live"),
    ("date_reception", "Reception"),
    ("date_end", "End"),
)


def _indicator_to_color(status: str) -> str:
    if status == "red":
        return "red"
    if status in {"orange", "amber"}:
        return "orange"
    return "green"


def compute_productivity_indicator(weekly: list[dict]) -> str:
    if len(weekly) < 2:
        return "orange"
    latest = weekly[-1]
    prev = weekly[-2]

    latest_real = to_float(latest.get("real_hours"))
    prev_real = to_float(prev.get("real_hours"))
    latest_progress = to_float(latest.get("progress_w"))
    prev_progress = to_float(prev.get("progress_w"))
    latest_theoretical = to_float(latest.get("horas_teoricas"))
    prev_theoretical = to_float(prev.get("horas_teoricas"))

    if (
        latest_real is None
        or prev_real is None
        or latest_progress is None
        or prev_progress is None
    ):
        return "orange"

    if latest_real > prev_real and latest_progress <= prev_progress:
        return "red"

    if latest_theoretical is not None and latest_real > latest_theoretical:
        return "amber"

    if prev_theoretical is not None and latest_real < prev_theoretical:
        return "green"

    return "orange"


def compute_deviation_indicator(weekly: list[dict]) -> str:
    if len(weekly) < 2:
        return "orange"
    latest = weekly[-1]
    prev = weekly[-2]

    latest_dev = to_float(latest.get("desviacion_pct"))
    prev_dev = to_float(prev.get("desviacion_pct"))
    if latest_dev is None or prev_dev is None:
        return "orange"
    if latest_dev > prev_dev:
        return "red"
    if latest_dev == prev_dev:
        return "amber"
    return "green"


def compute_phase_indicator(phases_history: list[dict]) -> str:
    changes: dict[str, dict[str, bool]] = {}
    for key, _label in PHASES_INFO:
        changes[key] = {"later": False, "earlier": False, "changed": False}

    for i in range(1, len(phases_history)):
        prev = phases_history[i - 1]
        curr = phases_history[i]
        for key, _label in PHASES_INFO:
            prev_date = prev.get(key)
            curr_date = curr.get(key)
            if prev_date != curr_date:
                changes[key]["changed"] = True
                direction = "unknown"
                if prev_date and curr_date:
                    if curr_date > prev_date:
                        direction = "later"
                    elif curr_date < prev_date:
                        direction = "earlier"
                if direction == "later":
                    changes[key]["later"] = True
                if direction == "earlier":
                    changes[key]["earlier"] = True

    for key, _label in PHASES_INFO:
        if changes[key]["later"]:
            return "red"
    for key, _label in PHASES_INFO:
        if changes[key]["earlier"]:
            return "green"
    for key, _label in PHASES_INFO:
        if changes[key]["changed"]:
            return "orange"
    return "orange"


# ---------- WEB ----------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/estado-proyecto", response_class=HTMLResponse)
def estado_proyecto(request: Request):
    return templates.TemplateResponse("project.html", {"request": request})


@app.get("/consultas", response_class=HTMLResponse)
def consultas(
    request: Request,
    equipo: str | None = None,
    order_phase: str | None = None,
):
    if equipo == "":
        equipo = None
    if order_phase == "":
        order_phase = None
    results, columns, numeric_columns = fetch_deviations_results(equipo, order_phase)
    teams, phases = fetch_filter_options()
    return templates.TemplateResponse(
        "queries.html",
        {
            "request": request,
            "results": results,
            "columns": columns,
            "numeric_columns": numeric_columns,
            "teams": teams,
            "phases": phases,
            "selected_team": equipo,
            "selected_phase": order_phase,
        },
    )


@app.get("/consultas/export")
def consultas_export(
    equipo: str | None = None,
    order_phase: str | None = None,
):
    if equipo == "":
        equipo = None
    if order_phase == "":
        order_phase = None
    results, columns, _numeric_columns = fetch_deviations_results(equipo, order_phase)
    df = pd.DataFrame(results, columns=columns)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    filename = "consultas_desviaciones.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(
        buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers=headers,
    )


@app.get("/projects/{project_code}/indicators", response_class=HTMLResponse)
def project_indicators(request: Request, project_code: str):
    project_name = None
    try:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_name
                    FROM projects
                    WHERE project_code = %s
                    """,
                    (project_code,),
                )
                row = cur.fetchone()
                if row:
                    project_name = row[0]
    except Exception:
        project_name = None
    return templates.TemplateResponse(
        "indicators.html",
        {"request": request, "project_code": project_code, "project_name": project_name},
    )

@app.get("/importacion", response_class=HTMLResponse)
def importacion(request: Request):
    return templates.TemplateResponse("import.html", {"request": request})

@app.get("/menu-personal", response_class=HTMLResponse)
def menu_personal(request: Request):
    pm_name = "Alvaro Blanco Pérez"
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id,
                       p.project_code,
                       p.project_name,
                       p.client,
                       p.team,
                       s.ordered_total,
                       s.ordered_n,
                       s.ordered_e,
                       s.real_hours,
                       s.desviacion_pct,
                       s.progress_w,
                       s.payment_inv
                FROM projects p
                LEFT JOIN LATERAL (
                    SELECT ordered_total,
                           ordered_n,
                           ordered_e,
                           real_hours,
                           desviacion_pct,
                           progress_w,
                           payment_inv
                    FROM project_snapshot
                    WHERE project_id = p.id
                    ORDER BY snapshot_year DESC, snapshot_week DESC, snapshot_at DESC
                    LIMIT 1
                ) s ON TRUE
                WHERE p.project_manager = %s
                """,
                (pm_name,),
            )
            rows = cur.fetchall()

    projects = []
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            for row in rows:
                project_id = row[0]
                cur.execute(
                    """
                    SELECT progress_w, desviacion_pct, real_hours, horas_teoricas
                    FROM project_snapshot
                    WHERE project_id = %s
                    ORDER BY snapshot_year ASC, snapshot_week ASC
                    """,
                    (project_id,),
                )
                weekly_rows = cur.fetchall()
                weekly = [
                    {
                        "progress_w": r[0],
                        "desviacion_pct": r[1],
                        "real_hours": r[2],
                        "horas_teoricas": r[3],
                    }
                    for r in weekly_rows
                ]

                cur.execute(
                    """
                    SELECT date_kickoff, date_design, date_validation,
                           date_golive, date_reception, date_end
                    FROM project_snapshot
                    WHERE project_id = %s
                    ORDER BY snapshot_year ASC, snapshot_week ASC
                    """,
                    (project_id,),
                )
                phase_rows = cur.fetchall()
                phases_history = [
                    {
                        "date_kickoff": r[0],
                        "date_design": r[1],
                        "date_validation": r[2],
                        "date_golive": r[3],
                        "date_reception": r[4],
                        "date_end": r[5],
                    }
                    for r in phase_rows
                ]

                productivity_status = compute_productivity_indicator(weekly)
                deviation_status = compute_deviation_indicator(weekly)
                phase_status = compute_phase_indicator(phases_history)
                indicator_statuses = [
                    _indicator_to_color(productivity_status),
                    _indicator_to_color(deviation_status),
                    _indicator_to_color(phase_status),
                ]
                if "red" in indicator_statuses:
                    overall_status = "red"
                elif "orange" in indicator_statuses:
                    overall_status = "orange"
                else:
                    overall_status = "green"

                ordered_total = row[5]
                if ordered_total is None and (row[6] is not None or row[7] is not None):
                    ordered_total = (row[6] or 0) + (row[7] or 0)
                projects.append(
                    {
                        "project_code": row[1],
                        "project_name": row[2],
                        "client": row[3],
                        "team": row[4],
                        "ordered_total": ordered_total,
                        "real_hours": row[8],
                        "desviacion_pct": row[9],
                        "progress_w": row[10],
                        "payment_inv": row[11],
                        "indicator_status": overall_status,
                    }
                )

    projects = sorted(projects, key=lambda item: (item["project_name"] or "").lower())

    return templates.TemplateResponse(
        "menu_personal.html",
        {"request": request, "pm_name": pm_name, "projects": projects},
    )


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


@app.get("/projects/{project_code}/metrics/weekly")
def project_weekly_metrics(project_code: str):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM projects
                WHERE project_code = %s
                """,
                (project_code,),
            )
            project_row = cur.fetchone()
            if not project_row:
                raise HTTPException(status_code=404, detail="Project not found")
            project_id = project_row[0]

            cur.execute(
                """
                SELECT snapshot_year, snapshot_week,
                       progress_w, desviacion_pct,
                       real_hours, horas_teoricas,
                       progress_w_delta, real_hours_delta,
                       horas_teoricas_delta, desviacion_pct_delta
                FROM project_snapshot
                WHERE project_id = %s
                ORDER BY snapshot_year ASC, snapshot_week ASC
                """,
                (project_id,),
            )
            rows = cur.fetchall()

    return [
        {
            "year": r[0],
            "week": r[1],
            "progress_w": to_float(r[2]),
            "desviacion_pct": to_float(r[3]),
            "real_hours": to_float(r[4]),
            "horas_teoricas": to_float(r[5]),
            "progress_w_delta": to_float(r[6]),
            "real_hours_delta": to_float(r[7]),
            "horas_teoricas_delta": to_float(r[8]),
            "desviacion_pct_delta": to_float(r[9]),
        }
        for r in rows
    ]


@app.get("/projects/{project_code}/metrics/phases")
def project_phase_history(project_code: str):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM projects
                WHERE project_code = %s
                """,
                (project_code,),
            )
            project_row = cur.fetchone()
            if not project_row:
                raise HTTPException(status_code=404, detail="Project not found")
            project_id = project_row[0]

            cur.execute(
                """
                SELECT snapshot_year, snapshot_week,
                       date_kickoff, date_design, date_validation,
                       date_golive, date_reception, date_end
                FROM project_snapshot
                WHERE project_id = %s
                ORDER BY snapshot_year ASC, snapshot_week ASC
                """,
                (project_id,),
            )
            rows = cur.fetchall()

    return [
        {
            "year": r[0],
            "week": r[1],
            "date_kickoff": to_date_iso(r[2]),
            "date_design": to_date_iso(r[3]),
            "date_validation": to_date_iso(r[4]),
            "date_golive": to_date_iso(r[5]),
            "date_reception": to_date_iso(r[6]),
            "date_end": to_date_iso(r[7]),
        }
        for r in rows
    ]


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
