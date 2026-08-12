"""Almacenamiento del Planning Gantt por proyecto.

Los items del Gantt viven en su propia tabla (`project_gantt_items`),
independiente de `project_snapshot`/`projects`: es una capa de
planificación editable por el PM que nunca escribe de vuelta en los
datos importados de OTS/AllOrders. El sembrado inicial (`seed_phase_items`)
solo copia las fechas de fase una vez, como punto de partida.
"""

from __future__ import annotations

from datetime import date

import psycopg

PHASE_DATE_COLUMNS = ("date_kickoff", "date_design", "date_validation", "date_golive", "date_reception", "date_end")


def ensure_project_gantt_storage(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS project_gantt_items (
            id BIGSERIAL PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            parent_id BIGINT REFERENCES project_gantt_items(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            is_milestone BOOLEAN NOT NULL DEFAULT FALSE,
            position INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'phase', 'checklist')),
            checklist_item_id BIGINT REFERENCES project_checklist_items(id) ON DELETE SET NULL,
            touched BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_project_gantt_items_project ON project_gantt_items (project_id, position);"
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_project_gantt_items_checklist
        ON project_gantt_items (checklist_item_id)
        WHERE checklist_item_id IS NOT NULL;
        """
    )


def fetch_latest_phase_dates(cur: psycopg.Cursor, project_id: int) -> dict[str, date | None] | None:
    cur.execute(
        f"""
        SELECT {', '.join(PHASE_DATE_COLUMNS)}
        FROM project_snapshot
        WHERE project_id = %s
        ORDER BY snapshot_year DESC, snapshot_week DESC
        LIMIT 1
        """,
        (project_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip(("kickoff", "design", "validation", "golive", "reception", "end"), row))


def seed_phase_items(cur: psycopg.Cursor, project_id: int) -> None:
    """Siembra las barras de fase iniciales a partir de las fechas del ultimo
    snapshot. Cada fase termina donde empieza la siguiente:
    Diseno = kickoff->design, Desarrollo = design->validation,
    HyperCare/Soporte = validation->end. Go-live y Recepcion se anaden
    como hitos puntuales. Solo se crean los tramos/hitos con fechas
    disponibles; no vuelve a ejecutarse si el proyecto ya tiene items
    (ver fetch_or_seed_items en router.py) para no pisar ediciones del PM.
    """
    dates = fetch_latest_phase_dates(cur, project_id)
    if not dates:
        return

    position = 0
    spans = [
        ("Diseño", dates["kickoff"], dates["design"]),
        ("Desarrollo", dates["design"], dates["validation"]),
        ("HyperCare / Soporte", dates["validation"], dates["end"]),
    ]
    for title, start, end in spans:
        if start is None or end is None:
            continue
        position += 1
        cur.execute(
            """
            INSERT INTO project_gantt_items (project_id, title, start_date, end_date, is_milestone, position, source)
            VALUES (%s, %s, %s, %s, FALSE, %s, 'phase')
            """,
            (project_id, title, start, end, position),
        )

    milestones = [("Go-live", dates["golive"]), ("Recepción", dates["reception"])]
    for title, when in milestones:
        if when is None:
            continue
        position += 1
        cur.execute(
            """
            INSERT INTO project_gantt_items (project_id, title, start_date, end_date, is_milestone, position, source)
            VALUES (%s, %s, %s, %s, TRUE, %s, 'phase')
            """,
            (project_id, title, when, when, position),
        )


def sync_checklist_milestone(
    cur: psycopg.Cursor,
    checklist_item_id: int,
    is_milestone: bool,
    project_id: int,
    task_text: str,
) -> None:
    """Crea/retira el item del Gantt vinculado a un checklist marcado como hito.

    Al marcarlo, se crea sin fecha fija (hoy, editable) a la espera de que el
    PM lo posicione. Al desmarcarlo: si el PM ya lo edito desde el Gantt
    (`touched = TRUE`) se conserva y solo se desvincula del checklist; si no
    se habia tocado, se borra.
    """
    if is_milestone:
        cur.execute(
            "SELECT id FROM project_gantt_items WHERE checklist_item_id = %s",
            (checklist_item_id,),
        )
        if cur.fetchone():
            return
        cur.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM project_gantt_items WHERE project_id = %s",
            (project_id,),
        )
        position = cur.fetchone()[0]
        today = date.today()
        cur.execute(
            """
            INSERT INTO project_gantt_items
                (project_id, title, start_date, end_date, is_milestone, position, source, checklist_item_id)
            VALUES (%s, %s, %s, %s, TRUE, %s, 'checklist', %s)
            """,
            (project_id, task_text, today, today, position, checklist_item_id),
        )
    else:
        cur.execute(
            "SELECT id, touched FROM project_gantt_items WHERE checklist_item_id = %s",
            (checklist_item_id,),
        )
        row = cur.fetchone()
        if not row:
            return
        item_id, touched = row
        if touched:
            cur.execute(
                "UPDATE project_gantt_items SET checklist_item_id = NULL, source = 'manual', updated_at = now() WHERE id = %s",
                (item_id,),
            )
        else:
            cur.execute("DELETE FROM project_gantt_items WHERE id = %s", (item_id,))
