from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple, List

import pandas as pd
import psycopg


# ---------------------------
# Helpers: normalize columns
# ---------------------------

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )

def _snake(s: str) -> str:
    s = str(s).strip()
    s = _strip_accents(s)           # <-- clave: elimina acentos
    s = s.lower()
    s = s.replace("%", "pct")
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _flatten_columns(cols) -> List[str]:
    """
    Flatten MultiIndex excel headers: ('Progress','%W') -> 'Progress %W'
    """
    out: List[str] = []
    for c in cols:
        if isinstance(c, tuple):
            a = "" if c[0] is None else str(c[0]).strip()
            b = "" if c[1] is None else str(c[1]).strip()
            if b.startswith("Unnamed"):
                out.append(a)
            elif a.startswith("Unnamed"):
                out.append(b)
            else:
                out.append(f"{a} {b}".strip())
        else:
            out.append(str(c).strip())
    return out


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, str) and v.strip() == "":
        return None
    try:
        n = float(v)
        if pd.isna(n):
            return None
        return n
    except Exception:
        return None


def _to_int(v) -> Optional[int]:
    f = _to_float(v)
    if f is None:
        return None
    try:
        return int(f)
    except Exception:
        return None


def _to_bool(v) -> Optional[bool]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "verdadero", "1", "yes", "y", "si", "sí"):
        return True
    if s in ("false", "falso", "0", "no", "n"):
        return False
    return None


def normalize_excel_date(v) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        if v.strip() == "":
            return None
        if re.match(r"^\d{5,}-\d{2}-\d{2}$", v.strip()):
            return None
        if re.match(r"^\d{5,}$", v.strip()):
            try:
                v = float(v.strip())
            except Exception:
                return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v == 0:
            return None
        try:
            d = pd.to_datetime(v, unit="D", origin="1899-12-30", errors="coerce")
            if pd.isna(d):
                return None
            return d.date()
        except Exception:
            return None
    try:
        d = pd.to_datetime(v, errors="coerce", dayfirst=True)
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


def _to_date(v) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        d = pd.to_datetime(v, errors="coerce")
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


from decimal import Decimal  # ponlo arriba con los imports

def _delta(curr, prev) -> Optional[float]:
    if curr is None or prev is None:
        return None

    # Normaliza Decimal -> float
    if isinstance(curr, Decimal):
        curr = float(curr)
    if isinstance(prev, Decimal):
        prev = float(prev)

    try:
        return float(curr) - float(prev)
    except Exception:
        return None



# ------------------------------------
# Excel -> normalized dataframe
# ------------------------------------

RENAME_MAP = {
    # progresos
    "progress_pctw": "progress_w",
    "progress_w": "progress_w",
    "progress_pctc": "progress_c",
    "progress_c": "progress_c",
    "progress_pctpm": "progress_pm",
    "progress_pm": "progress_pm",
    "progress_pcte": "progress_e",
    "progress_e": "progress_e",

    # deviations (excel direct)
    "desviacion_h": "excel_desviacion_h",
    "desviacion_pct": "excel_desviacion_pct",
    "horas_teoricas": "excel_horas_teoricas",
}


def _read_excel_try(path: str, sheet: str, header_mode) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet, header=header_mode, engine="openpyxl")


def read_and_normalize_excel(path: str, sheet: Optional[str]) -> pd.DataFrame:
    """
    Lee Excel con cabecera de 2 filas si aplica.
    Si el Excel viene "antiguo" (1 fila), reintenta con header=0.
    """
    xls = pd.ExcelFile(path, engine="openpyxl")
    if sheet is None or str(sheet).strip() == "":
        sheet = xls.sheet_names[0]
    if sheet not in xls.sheet_names:
        raise ValueError(f"Worksheet named '{sheet}' not found. Available sheets: {xls.sheet_names}")

    # 1) intentamos 2-row header
    try:
        df = _read_excel_try(path, sheet, header_mode=[0, 1])
        # si no es MultiIndex, o se queda raro, caeremos al fallback
        if not isinstance(df.columns, pd.MultiIndex):
            raise ValueError("Not a MultiIndex header")
        flat = _flatten_columns(df.columns)
        df.columns = [_snake(c) for c in flat]
    except Exception:
        # 2) fallback: 1-row header
        df = _read_excel_try(path, sheet, header_mode=0)
        df.columns = [_snake(c) for c in df.columns]

    # apply rename map
    df = df.rename(columns={c: RENAME_MAP.get(c, c) for c in df.columns})

    # Aliases entre Excels
    ALIASES = {
        "customer": "client",
        "code": "project_code",
        "projectmanager": "project_manager",
        "real": "real_hours",

        # deviation pct naming quirks
        "deviation_pcttd": "deviation_td",
        "deviation_pctcd": "deviation_cd",
        "deviation_pctpmd": "deviation_pmd",
        "deviation_pcted": "deviation_ed",

        # checks ok
        "kick_off_ok": "kickoff_ok",
        "go_live_ok": "golive_ok",

        # report date
        "date": "report_date",

        # milestone dates (grouped under Dates)
        "dates_k": "date_kickoff",
        "dates_d": "date_design",
        "dates_v": "date_validation",
        "dates_g": "date_golive",
        "dates_r": "date_reception",
        "dates_e": "date_end",
    }
    for src, dst in ALIASES.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})

    # Fixes típicos con "unnamed_*" (cuando venía multiheader y se aplana raro)
    auto_rename = {
        "project_name_unnamed_0_level_1": "project_name",
        "customer_unnamed_1_level_1": "client",
        "code_unnamed_2_level_1": "project_code",
        "mp_unnamed_3_level_1": "mp",
        "team_unnamed_4_level_1": "team",
        "projectmanager_unnamed_8_level_1": "project_manager",
        "consultant_unnamed_9_level_1": "consultant",
        "order_phase_unnamed_22_level_1": "order_phase",
        "internal_status_unnamed_23_level_1": "internal_status",
        "project_type_unnamed_24_level_1": "project_type",
        "service_type_unnamed_25_level_1": "service_type",
        "offer_code_unnamed_26_level_1": "offer_code",
        "date_unnamed_27_level_1": "report_date",
        "dates_k_unnamed_28_level_1": "date_kickoff",
        "dates_d_unnamed_29_level_1": "date_design",
        "dates_v_unnamed_30_level_1": "date_validation",
        "dates_g_unnamed_31_level_1": "date_golive",
        "dates_r_unnamed_32_level_1": "date_reception",
        "dates_e_unnamed_33_level_1": "date_end",
        "kick_off_ok_unnamed_34_level_1": "kickoff_ok",
        "design_ok_unnamed_35_level_1": "design_ok",
        "validation_ok_unnamed_36_level_1": "validation_ok",
        "go_live_ok_unnamed_37_level_1": "golive_ok",
        "reception_ok_unnamed_38_level_1": "reception_ok",
        "end_ok_unnamed_39_level_1": "end_ok",

        # real_hours cambia de posición según export
        "real_unnamed_54_level_1": "real_hours",
        "real_unnamed_49_level_1": "real_hours",
    }
    for src, dst in auto_rename.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})

    # Fuerza renombres de desviación (por si entran con nombres raros)
    if "desviacion_h" in df.columns and "excel_desviacion_h" not in df.columns:
        df = df.rename(columns={"desviacion_h": "excel_desviacion_h"})
    if "desviacion_pct" in df.columns and "excel_desviacion_pct" not in df.columns:
        df = df.rename(columns={"desviacion_pct": "excel_desviacion_pct"})
    if "horas_teoricas" in df.columns and "excel_horas_teoricas" not in df.columns:
        df = df.rename(columns={"horas_teoricas": "excel_horas_teoricas"})

    # Debug
    print("DEBUG real candidates:", [c for c in df.columns if "real" in c.lower()])
    print("DEBUG ordered candidates:", [c for c in df.columns if "ordered" in c.lower()])
    print("DEBUG df.shape:", df.shape)
    print("DEBUG df.columns (first 40):", list(df.columns)[:40])

    return df


# ------------------------------------
# DB upserts
# ------------------------------------

def upsert_project(cur: psycopg.Cursor, project: Dict[str, Any]) -> int:
    """
    Upsert into projects by project_code. Returns project_id.
    """
    sql = """
    INSERT INTO projects (
        project_code, project_name, client, company, team, project_manager, consultant, status
    )
    VALUES (
        %(project_code)s, %(project_name)s, %(client)s, %(company)s, %(team)s, %(project_manager)s, %(consultant)s, %(status)s
    )
    ON CONFLICT (project_code)
    DO UPDATE SET
        project_name     = COALESCE(EXCLUDED.project_name, projects.project_name),
        client           = COALESCE(EXCLUDED.client, projects.client),
        company          = COALESCE(EXCLUDED.company, projects.company),
        team             = COALESCE(EXCLUDED.team, projects.team),
        project_manager  = COALESCE(EXCLUDED.project_manager, projects.project_manager),
        consultant       = COALESCE(EXCLUDED.consultant, projects.consultant),
        status           = COALESCE(EXCLUDED.status, projects.status)
    RETURNING id;
    """
    cur.execute(sql, project)
    return cur.fetchone()[0]


def fetch_prev_snapshot(
    cur: psycopg.Cursor,
    project_id: int,
    snapshot_year: int,
    snapshot_week: int,
) -> Optional[Dict[str, Any]]:
    sql = """
    SELECT
      progress_w, real_hours, ordered_total, horas_teoricas, desviacion_pct,
      date_kickoff, date_design, date_validation, date_golive, date_reception, date_end
    FROM project_snapshot
    WHERE project_id = %s
      AND (snapshot_year, snapshot_week) < (%s, %s)
    ORDER BY snapshot_year DESC, snapshot_week DESC
    LIMIT 1;
    """
    cur.execute(sql, (project_id, snapshot_year, snapshot_week))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "progress_w": row[0],
        "real_hours": row[1],
        "ordered_total": row[2],
        "horas_teoricas": row[3],
        "desviacion_pct": row[4],
        "date_kickoff": row[5],
        "date_design": row[6],
        "date_validation": row[7],
        "date_golive": row[8],
        "date_reception": row[9],
        "date_end": row[10],
    }


def upsert_snapshot(
    cur: psycopg.Cursor,
    project_id: int,
    import_file_id: Optional[int],
    snapshot_year: int,
    snapshot_week: int,
    fields: Dict[str, Any],
) -> int:
    payload = dict(fields)
    for key in (
        "date_kickoff",
        "date_design",
        "date_validation",
        "date_golive",
        "date_reception",
        "date_end",
    ):
        if payload.get(key) == "":
            payload[key] = None
    payload.update({
        "project_id": project_id,
        "import_file_id": import_file_id,
        "snapshot_year": snapshot_year,
        "snapshot_week": snapshot_week,
    })

    sql = """
    INSERT INTO project_snapshot (
      project_id, import_file_id, snapshot_year, snapshot_week, snapshot_at,

      progress_w, progress_c, progress_pm, progress_e, progress_ed,
      deviation_td, deviation_cd, deviation_pmd, deviation_ed,

      payment_inv, payment_total, payment_pending, payment_q,

      date_kickoff, date_design, date_validation, date_golive, date_reception, date_end,

      team, project_manager, consultant, order_phase, internal_status, project_type, service_type, offer_code, report_date, comments,
      kickoff_ok, design_ok, validation_ok, golive_ok, reception_ok, end_ok,
      mp,

      ordered_n, ordered_e, ordered_total,
      real_hours,
      horas_teoricas,
      desviacion_h,
      desviacion_pct,

      progress_w_delta, real_hours_delta, ordered_total_delta, horas_teoricas_delta, desviacion_pct_delta,
      productividad_proyecto

    )
    VALUES (
      %(project_id)s, %(import_file_id)s, %(snapshot_year)s, %(snapshot_week)s, now(),

      %(progress_w)s, %(progress_c)s, %(progress_pm)s, %(progress_e)s, %(progress_ed)s,
      %(deviation_td)s, %(deviation_cd)s, %(deviation_pmd)s, %(deviation_ed)s,

      %(payment_inv)s, %(payment_total)s, %(payment_pending)s, %(payment_q)s,

      %(date_kickoff)s, %(date_design)s, %(date_validation)s, %(date_golive)s, %(date_reception)s, %(date_end)s,

      %(team)s, %(project_manager)s, %(consultant)s, %(order_phase)s, %(internal_status)s, %(project_type)s, %(service_type)s, %(offer_code)s, %(report_date)s, %(comments)s,
      %(kickoff_ok)s, %(design_ok)s, %(validation_ok)s, %(golive_ok)s, %(reception_ok)s, %(end_ok)s,
      %(mp)s,

      %(ordered_n)s, %(ordered_e)s, %(ordered_total)s,
      %(real_hours)s,
      %(horas_teoricas)s,
      %(desviacion_h)s,
      %(desviacion_pct)s,

      %(progress_w_delta)s, %(real_hours_delta)s, %(ordered_total_delta)s, %(horas_teoricas_delta)s, %(desviacion_pct_delta)s,
      %(productividad_proyecto)s

      
    )
    ON CONFLICT (project_id, snapshot_year, snapshot_week)
    DO UPDATE SET
      import_file_id = COALESCE(EXCLUDED.import_file_id, project_snapshot.import_file_id),
      snapshot_at = now(),

      progress_w = COALESCE(EXCLUDED.progress_w, project_snapshot.progress_w),
      progress_c = COALESCE(EXCLUDED.progress_c, project_snapshot.progress_c),
      progress_pm = COALESCE(EXCLUDED.progress_pm, project_snapshot.progress_pm),
      progress_e = COALESCE(EXCLUDED.progress_e, project_snapshot.progress_e),
      progress_ed = COALESCE(EXCLUDED.progress_ed, project_snapshot.progress_ed),

      deviation_td = COALESCE(EXCLUDED.deviation_td, project_snapshot.deviation_td),
      deviation_cd = COALESCE(EXCLUDED.deviation_cd, project_snapshot.deviation_cd),
      deviation_pmd = COALESCE(EXCLUDED.deviation_pmd, project_snapshot.deviation_pmd),
      deviation_ed = COALESCE(EXCLUDED.deviation_ed, project_snapshot.deviation_ed),

      payment_inv = COALESCE(EXCLUDED.payment_inv, project_snapshot.payment_inv),
      payment_total = COALESCE(EXCLUDED.payment_total, project_snapshot.payment_total),
      payment_pending = COALESCE(EXCLUDED.payment_pending, project_snapshot.payment_pending),
      payment_q = COALESCE(EXCLUDED.payment_q, project_snapshot.payment_q),

      date_kickoff = EXCLUDED.date_kickoff,
      date_design = EXCLUDED.date_design,
      date_validation = EXCLUDED.date_validation,
      date_golive = EXCLUDED.date_golive,
      date_reception = EXCLUDED.date_reception,
      date_end = EXCLUDED.date_end,

      team = COALESCE(EXCLUDED.team, project_snapshot.team),
      project_manager = COALESCE(EXCLUDED.project_manager, project_snapshot.project_manager),
      consultant = COALESCE(EXCLUDED.consultant, project_snapshot.consultant),
      order_phase = COALESCE(EXCLUDED.order_phase, project_snapshot.order_phase),
      internal_status = COALESCE(EXCLUDED.internal_status, project_snapshot.internal_status),
      project_type = COALESCE(EXCLUDED.project_type, project_snapshot.project_type),
      service_type = COALESCE(EXCLUDED.service_type, project_snapshot.service_type),
      offer_code = COALESCE(EXCLUDED.offer_code, project_snapshot.offer_code),
      report_date = COALESCE(EXCLUDED.report_date, project_snapshot.report_date),
      comments = COALESCE(EXCLUDED.comments, project_snapshot.comments),

      kickoff_ok = COALESCE(EXCLUDED.kickoff_ok, project_snapshot.kickoff_ok),
      design_ok = COALESCE(EXCLUDED.design_ok, project_snapshot.design_ok),
      validation_ok = COALESCE(EXCLUDED.validation_ok, project_snapshot.validation_ok),
      golive_ok = COALESCE(EXCLUDED.golive_ok, project_snapshot.golive_ok),
      reception_ok = COALESCE(EXCLUDED.reception_ok, project_snapshot.reception_ok),
      end_ok = COALESCE(EXCLUDED.end_ok, project_snapshot.end_ok),
      mp = COALESCE(EXCLUDED.mp, project_snapshot.mp),

      ordered_n = COALESCE(EXCLUDED.ordered_n, project_snapshot.ordered_n),
      ordered_e = COALESCE(EXCLUDED.ordered_e, project_snapshot.ordered_e),
      ordered_total = COALESCE(EXCLUDED.ordered_total, project_snapshot.ordered_total),

      real_hours = COALESCE(EXCLUDED.real_hours, project_snapshot.real_hours),
      horas_teoricas = COALESCE(EXCLUDED.horas_teoricas, project_snapshot.horas_teoricas),
      desviacion_h = COALESCE(EXCLUDED.desviacion_h, project_snapshot.desviacion_h),
      desviacion_pct = COALESCE(EXCLUDED.desviacion_pct, project_snapshot.desviacion_pct),

      progress_w_delta = COALESCE(EXCLUDED.progress_w_delta, project_snapshot.progress_w_delta),
      real_hours_delta = COALESCE(EXCLUDED.real_hours_delta, project_snapshot.real_hours_delta),
      ordered_total_delta = COALESCE(EXCLUDED.ordered_total_delta, project_snapshot.ordered_total_delta),
      horas_teoricas_delta = COALESCE(EXCLUDED.horas_teoricas_delta, project_snapshot.horas_teoricas_delta),
      desviacion_pct_delta = COALESCE(EXCLUDED.desviacion_pct_delta, project_snapshot.desviacion_pct_delta),
      productividad_proyecto = COALESCE(EXCLUDED.productividad_proyecto, project_snapshot.productividad_proyecto)



    RETURNING id;
    """
    cur.execute(sql, payload)
    return cur.fetchone()[0]


# ------------------------------------
# Row mapping + computed fields
# ------------------------------------

def map_row(row: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    project_code = row.get("project_code")
    if project_code is None or (isinstance(project_code, float) and pd.isna(project_code)):
        return {}, {}

    code_int = _to_int(project_code)
    project = {
        "project_code": str(code_int) if code_int is not None else str(project_code),
        "project_name": row.get("project_name"),
        "client": row.get("client"),
        "company": row.get("company"),
        "team": row.get("team"),
        "project_manager": row.get("project_manager"),
        "consultant": row.get("consultant"),
        "status": row.get("status"),
    }

    ordered_n = _to_float(row.get("ordered_n"))
    ordered_e = _to_float(row.get("ordered_e"))
    ordered_total = None
    if ordered_n is not None or ordered_e is not None:
        ordered_total = (ordered_n or 0.0) + (ordered_e or 0.0)

    progress_w = _to_float(row.get("progress_w"))
    real_hours = _to_float(row.get("real_hours"))

    horas_teoricas = None
    if ordered_total is not None and progress_w is not None:
        horas_teoricas = ordered_total * (progress_w / 100.0)

    desviacion_h = None
    if real_hours is not None and horas_teoricas is not None:
        desviacion_h = real_hours - horas_teoricas

    desviacion_pct = None
    if desviacion_h is not None and horas_teoricas not in (None, 0) and abs(horas_teoricas) > 1e-6:
        desviacion_pct = (desviacion_h / horas_teoricas) * 100.0


    snap = {
        "progress_w": progress_w,
        "progress_c": _to_float(row.get("progress_c")),
        "progress_pm": _to_float(row.get("progress_pm")),
        "progress_e": _to_float(row.get("progress_e")),
        "progress_ed": _to_float(row.get("progress_ed")),

        "deviation_td": _to_float(row.get("deviation_td")),
        "deviation_cd": _to_float(row.get("deviation_cd")),
        "deviation_pmd": _to_float(row.get("deviation_pmd")),
        "deviation_ed": _to_float(row.get("deviation_ed")),

        "payment_inv": _to_float(row.get("payment_inv")),
        "payment_total": _to_float(row.get("payment_total")),
        "payment_pending": _to_float(row.get("payment_pending")),
        "payment_q": _to_float(row.get("payment_q")),

        "date_kickoff": normalize_excel_date(row.get("date_kickoff")),
        "date_design": normalize_excel_date(row.get("date_design")),
        "date_validation": normalize_excel_date(row.get("date_validation")),
        "date_golive": normalize_excel_date(row.get("date_golive")),
        "date_reception": normalize_excel_date(row.get("date_reception")),
        "date_end": normalize_excel_date(row.get("date_end")),

        "team": row.get("team"),
        "project_manager": row.get("project_manager"),
        "consultant": row.get("consultant"),
        "order_phase": row.get("order_phase"),
        "internal_status": row.get("internal_status"),
        "project_type": row.get("project_type"),
        "service_type": row.get("service_type"),
        "offer_code": row.get("offer_code"),
        "report_date": _to_date(row.get("report_date")),
        "comments": row.get("comments"),

        "kickoff_ok": _to_bool(row.get("kickoff_ok")),
        "design_ok": _to_bool(row.get("design_ok")),
        "validation_ok": _to_bool(row.get("validation_ok")),
        "golive_ok": _to_bool(row.get("golive_ok")),
        "reception_ok": _to_bool(row.get("reception_ok")),
        "end_ok": _to_bool(row.get("end_ok")),
        "mp": _to_bool(row.get("mp")),

        "ordered_n": ordered_n,
        "ordered_e": ordered_e,
        "ordered_total": ordered_total,
        "real_hours": real_hours,
        "horas_teoricas": horas_teoricas,
        "desviacion_h": desviacion_h,
        "desviacion_pct": desviacion_pct,

        "progress_w_delta": None,
        "real_hours_delta": None,
        "ordered_total_delta": None,
        "horas_teoricas_delta": None,
        "desviacion_pct_delta": None,
        "productividad_proyecto": None,
    }

    return project, snap


def compute_deltas(
    cur: psycopg.Cursor,
    project_id: int,
    snapshot_year: int,
    snapshot_week: int,
    snap_fields: Dict[str, Any],
) -> Dict[str, Any]:
    prev = fetch_prev_snapshot(cur, project_id, snapshot_year, snapshot_week)
    if not prev:
        return snap_fields

    snap_fields["progress_w_delta"] = _delta(snap_fields.get("progress_w"), prev.get("progress_w"))
    snap_fields["real_hours_delta"] = _delta(snap_fields.get("real_hours"), prev.get("real_hours"))
    snap_fields["ordered_total_delta"] = _delta(snap_fields.get("ordered_total"), prev.get("ordered_total"))
    snap_fields["horas_teoricas_delta"] = _delta(snap_fields.get("horas_teoricas"), prev.get("horas_teoricas"))
    snap_fields["desviacion_pct_delta"] = _delta(snap_fields.get("desviacion_pct"), prev.get("desviacion_pct"))

    rhd = snap_fields.get("real_hours_delta")
    htd = snap_fields.get("horas_teoricas_delta")
    if rhd is None or htd in (None, 0) or abs(htd) <= 1e-6:
        snap_fields["productividad_proyecto"] = None
    else:
        snap_fields["productividad_proyecto"] = rhd / htd


    return snap_fields
