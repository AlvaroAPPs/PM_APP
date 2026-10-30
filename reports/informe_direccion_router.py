from __future__ import annotations

import io
import json
from datetime import date

import psycopg
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from reports.informe_direccion import (
    DB_DSN,
    DEFAULT_PROJECT_TYPES,
    DEFAULT_TEAMS,
    TIPO_DIRECCION,
    TIPO_INTERNO,
    completar_detalles,
    crear_corte,
    datos_presentacion,
    ensure_informe_storage,
    fetch_filter_options,
    fetch_import_options,
    get_corte,
    list_cortes,
    recalcular_corte,
)
from reports.informe_direccion_pptx import generar_presentacion
from reports.informe_objetivos import (
    HITO_TITULOS,
    datos_objetivos,
    ensure_objetivos_storage,
    serializar,
    set_motivo,
    set_nombre,
)
from reports.informe_sync import (
    contar_conflictos,
    ensure_sync_storage,
    exportar,
    importar,
    leer_fichero,
    listar_conflictos,
    mi_nombre,
    resolver_conflicto,
)

router = APIRouter(tags=["informe-direccion"])
templates = Jinja2Templates(directory="templates")

PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class CorteCreateIn(BaseModel):
    fecha_corte: date
    tipo: str = TIPO_DIRECCION
    all_orders_import_id: int
    ots_import_id: int | None = None
    equipos: list[str]
    tipos_proyecto: list[str]


class CorteUpdateIn(BaseModel):
    tipo: str


class NombreIn(BaseModel):
    nombre: str


class MotivoIn(BaseModel):
    project_code: str
    hito: str
    motivo: str


class ConflictoIn(BaseModel):
    accion: str


def _validate_tipo(tipo: str) -> str:
    tipo = (tipo or "").strip().upper()
    if tipo not in (TIPO_DIRECCION, TIPO_INTERNO):
        raise HTTPException(status_code=400, detail="Tipo debe ser DIRECCION o INTERNO")
    return tipo


def _corte_or_404(cur: psycopg.Cursor, corte_id: int) -> dict:
    corte = get_corte(cur, corte_id)
    if corte is None:
        raise HTTPException(status_code=404, detail="Corte no encontrado")
    return corte


def _check_all_orders_has_progress(cur: psycopg.Cursor, import_id: int) -> None:
    cur.execute(
        "SELECT COUNT(*), COUNT(status_pct) FROM all_orders_snapshot WHERE import_file_id = %s",
        (import_id,),
    )
    rows, with_progress = cur.fetchone()
    if not rows:
        raise HTTPException(status_code=400, detail="La importacion elegida no es un AllOrders")
    if not with_progress:
        raise HTTPException(
            status_code=400,
            detail="Este AllOrders se importo antes de guardar el avance (Status %) y la facturacion. "
                   "Vuelve a importarlo y usa la nueva importacion.",
        )


def _corte_out(corte: dict, filenames: dict[int, str]) -> dict:
    metricas = corte["metricas"] or {}
    return {
        "id": corte["id"],
        "fecha_corte": corte["fecha_corte"].isoformat(),
        "tipo": corte["tipo"],
        "origen": corte["origen"],
        "all_orders": filenames.get(corte["all_orders_import_id"]),
        "ots": filenames.get(corte["ots_import_id"]),
        "puede_recalcular": bool(corte["all_orders_import_id"]),
        "proyectos": (metricas.get("proyectos") or {}).get("totales"),
        "horas": (metricas.get("horas") or {}).get("totales"),
        "equipos": corte["equipos"] or [],
        "importado_de": corte.get("importado_de"),
    }


@router.get("/informes/direccion")
def informe_direccion_page(request: Request):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_sync_storage(cur)
            completar_detalles(cur)
            cortes = list_cortes(cur)
            cur.execute("SELECT id, filename FROM import_file")
            filenames = dict(cur.fetchall())
            opciones = fetch_import_options(cur)
            conflictos = contar_conflictos(cur)
            yo = mi_nombre(cur)
        conn.commit()
    return templates.TemplateResponse(
        "informe_direccion.html",
        {
            "request": request,
            "cortes": [_corte_out(c, filenames) for c in reversed(cortes)],
            "opciones": opciones,
            "default_teams": DEFAULT_TEAMS,
            "default_types": DEFAULT_PROJECT_TYPES,
            "today": date.today().isoformat(),
            "conflictos": conflictos,
            "yo": yo,
        },
    )


@router.get("/api/informe-direccion/exportar")
def informe_direccion_exportar():
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            try:
                blob, filename = exportar(cur)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/informe-direccion/importar")
async def informe_direccion_importar(file: UploadFile = File(...)):
    try:
        data = leer_fichero(await file.read())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            try:
                resumen = importar(cur, data)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
    return resumen


@router.get("/api/informe-direccion/conflictos")
def informe_direccion_conflictos():
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_sync_storage(cur)
            result = {"yo": mi_nombre(cur), "conflictos": listar_conflictos(cur)}
        conn.commit()
    return json.loads(json.dumps(result, default=str))


@router.post("/api/informe-direccion/conflictos/{tipo}/{project_code}")
def informe_direccion_resolver(tipo: str, project_code: str, payload: ConflictoIn):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_sync_storage(cur)
            yo = mi_nombre(cur)
            if not yo:
                raise HTTPException(status_code=400, detail="Configura tu nombre de PM en Configuración.")
            try:
                resolver_conflicto(cur, yo, tipo, project_code, payload.accion)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
    return {"ok": True}


@router.get("/api/informe-direccion/importaciones/{import_id}/filtros")
def informe_direccion_filtros(import_id: int):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            return fetch_filter_options(cur, import_id)


@router.post("/api/informe-direccion/cortes")
def informe_direccion_crear(payload: CorteCreateIn):
    tipo = _validate_tipo(payload.tipo)
    equipos = [e.strip() for e in payload.equipos if e and e.strip()]
    tipos = [t.strip() for t in payload.tipos_proyecto if t and t.strip()]
    if not equipos or not tipos:
        raise HTTPException(status_code=400, detail="Selecciona al menos un equipo y un tipo de proyecto")
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_informe_storage(cur)
            _check_all_orders_has_progress(cur, payload.all_orders_import_id)
            corte_id = crear_corte(cur, payload.fecha_corte, tipo, payload.all_orders_import_id,
                                   payload.ots_import_id, equipos, tipos)
        conn.commit()
    return {"id": corte_id}


@router.patch("/api/informe-direccion/cortes/{corte_id}")
def informe_direccion_actualizar(corte_id: int, payload: CorteUpdateIn):
    tipo = _validate_tipo(payload.tipo)
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            _corte_or_404(cur, corte_id)
            cur.execute("UPDATE informe_cortes SET tipo = %s, updated_at = now() WHERE id = %s", (tipo, corte_id))
        conn.commit()
    return {"ok": True}


@router.post("/api/informe-direccion/cortes/{corte_id}/recalcular")
def informe_direccion_recalcular(corte_id: int):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            corte = _corte_or_404(cur, corte_id)
            if corte["all_orders_import_id"]:
                _check_all_orders_has_progress(cur, corte["all_orders_import_id"])
            try:
                recalcular_corte(cur, corte)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
    return {"ok": True}


@router.delete("/api/informe-direccion/cortes/{corte_id}")
def informe_direccion_borrar(corte_id: int):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            _corte_or_404(cur, corte_id)
            cur.execute("DELETE FROM informe_cortes WHERE id = %s", (corte_id,))
        conn.commit()
    return {"ok": True}


@router.get("/api/informe-direccion/cortes/{corte_id}/resumen")
def informe_direccion_resumen(corte_id: int):
    """Vista previa: con que corte se compara y entradas/salidas resultantes."""
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            datos = datos_presentacion(cur, _corte_or_404(cur, corte_id))
    anterior = datos["anterior"]
    return json.loads(json.dumps({
        "anterior": anterior["fecha_corte"].isoformat() if anterior else None,
        "aviso_delta": datos["aviso_delta"],
        "delta": datos["delta"],
        "puntos_historico": len(datos["historico"]),
    }, default=str))


@router.get("/informes/direccion/{corte_id}/objetivos")
def informe_direccion_objetivos_page(request: Request, corte_id: int):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            corte = _corte_or_404(cur, corte_id)
    return templates.TemplateResponse(
        "informe_direccion_objetivos.html",
        {"request": request, "corte_id": corte_id, "fecha_corte": corte["fecha_corte"].isoformat(),
         "tipo": corte["tipo"]},
    )


@router.get("/api/informe-direccion/cortes/{corte_id}/objetivos")
def informe_direccion_objetivos(corte_id: int):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            datos = datos_objetivos(cur, _corte_or_404(cur, corte_id))
        conn.commit()
    return serializar(datos)


@router.put("/api/informe-direccion/nombres/{project_code}")
def informe_direccion_nombre(project_code: str, payload: NombreIn):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_objetivos_storage(cur)
            set_nombre(cur, project_code, payload.nombre)
        conn.commit()
    return {"ok": True}


@router.put("/api/informe-direccion/cortes/{corte_id}/motivos")
def informe_direccion_motivo(corte_id: int, payload: MotivoIn):
    if payload.hito not in HITO_TITULOS:
        raise HTTPException(status_code=400, detail="Hito no valido")
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            _corte_or_404(cur, corte_id)
            ensure_objetivos_storage(cur)
            set_motivo(cur, corte_id, payload.project_code, payload.hito, payload.motivo)
        conn.commit()
    return {"ok": True}


@router.get("/informes/direccion/{corte_id}.pptx")
def informe_direccion_pptx(corte_id: int):
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            datos = datos_presentacion(cur, _corte_or_404(cur, corte_id))
            objetivos = datos_objetivos(cur, datos["corte"])
        conn.commit()
    corte = datos["corte"]
    if not corte["metricas"].get("tramos"):
        raise HTTPException(status_code=400, detail="Este corte no tiene los datos de los graficos de tramos")
    blob = generar_presentacion(corte, datos["historico"], datos["delta"], datos["entregas_anterior"], objetivos)
    filename = f"Estado Ampliaciones {corte['fecha_corte'].isoformat()}.pptx"
    return StreamingResponse(
        io.BytesIO(blob),
        media_type=PPTX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
