"""Motor PDF minimalista y multi-pagina, sin dependencias externas.

Adaptado de las primitivas de dibujo de app.py (_pdf_text/_pdf_rect/
_pdf_grouped_bar_chart/_pdf_multi_line_chart), que solo ensamblaban una
pagina. Aqui se generaliza a N paginas y se declara /Encoding
/WinAnsiEncoding en las fuentes para que los acentos y la enie del
espanol se rendericen correctamente.
"""

from __future__ import annotations

import re

PAGE_WIDTH = 842.0
PAGE_HEIGHT = 595.0


def _pdf_escape(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return re.sub(r"[\x00-\x1F]", " ", text)


def pdf_text(
    stream: list[str],
    x: float,
    y: float,
    text: str,
    size: int = 9,
    bold: bool = False,
    color_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    font = "F2" if bold else "F1"
    stream.extend([
        "BT",
        f"/{font} {size} Tf",
        f"{color_rgb[0]:.2f} {color_rgb[1]:.2f} {color_rgb[2]:.2f} rg",
        f"1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_escape(text)}) Tj",
        "ET",
    ])


def pdf_rect(
    stream: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    fill_rgb: tuple[float, float, float] | None = None,
    stroke_rgb: tuple[float, float, float] | None = (0.82, 0.85, 0.90),
    line_width: float = 0.7,
) -> None:
    if fill_rgb is not None:
        stream.append(f"{fill_rgb[0]:.2f} {fill_rgb[1]:.2f} {fill_rgb[2]:.2f} rg")
    if stroke_rgb is not None:
        stream.append(f"{stroke_rgb[0]:.2f} {stroke_rgb[1]:.2f} {stroke_rgb[2]:.2f} RG")
        stream.append(f"{line_width:.2f} w")
    stream.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {'B' if fill_rgb is not None and stroke_rgb is not None else 'f' if fill_rgb is not None else 'S'}")


def pdf_line(
    stream: list[str],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color_rgb: tuple[float, float, float] = (0.85, 0.86, 0.90),
    line_width: float = 0.6,
) -> None:
    stream.append(f"{color_rgb[0]:.2f} {color_rgb[1]:.2f} {color_rgb[2]:.2f} RG {line_width:.2f} w")
    stream.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")


def pdf_multi_line_chart(
    stream: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    labels: list[str],
    series: list[tuple[str, tuple[float, float, float], list[float | None]]],
    show_value_labels: bool = True,
) -> None:
    pdf_rect(stream, x, y, w, h, fill_rgb=(1.0, 1.0, 1.0), stroke_rgb=(0.86, 0.88, 0.92), line_width=0.8)
    pdf_text(stream, x + 8, y + h - 14, title, size=9, bold=True)

    chart_x = x + 34
    chart_y = y + 20
    chart_w = w - 50
    chart_h = h - 60

    numeric = [value for _name, _color, values in series for value in values if value is not None]
    if len(numeric) < 1:
        pdf_text(stream, x + 8, y + 8, "Sin datos", size=8)
        return

    vmin = min(0.0, min(numeric))
    vmax = max(numeric)
    if vmin == vmax:
        vmax += 1.0
    pad = (vmax - vmin) * 0.08
    vmax += pad

    for idx in range(5):
        gy = chart_y + (chart_h * idx / 4)
        stream.append("0.93 0.94 0.96 RG 0.4 w")
        stream.append(f"{chart_x:.2f} {gy:.2f} m {chart_x + chart_w:.2f} {gy:.2f} l S")

    stream.append("0.60 0.64 0.72 RG 0.7 w")
    stream.append(f"{chart_x:.2f} {chart_y:.2f} m {chart_x:.2f} {chart_y + chart_h:.2f} l S")
    stream.append(f"{chart_x:.2f} {chart_y:.2f} m {chart_x + chart_w:.2f} {chart_y:.2f} l S")

    for idx, label in enumerate(labels):
        px = chart_x + (chart_w * idx / max(1, len(labels) - 1))
        stream.append("0.80 0.82 0.88 RG 0.3 w")
        stream.append(f"{px:.2f} {chart_y:.2f} m {px:.2f} {chart_y - 3:.2f} l S")
        pdf_text(stream, px - 9, chart_y - 12, label, size=6.5)

    for tick in range(5):
        value = vmin + ((vmax - vmin) * tick / 4)
        py = chart_y + (chart_h * tick / 4)
        pdf_text(stream, x + 2, py - 2, f"{value:,.0f}".replace(",", "."), size=6.5)

    legend_slot = min(150, (w - 16) / max(1, len(series)))
    legend_x = max(chart_x, x + (w - (len(series) * legend_slot)) / 2)
    legend_y = y + h - 28
    # Cuando varias series coinciden exactamente en un punto (muy habitual
    # en meses ya cerrados, donde "hoy"/"hace 1 semana"/"hace 4 semanas"
    # todavia no han divergido) solo se imprime el valor una vez por punto,
    # para no apilar el mismo numero repetido.
    printed_at_index: dict[int, set[float]] = {}
    for series_idx, (name, color, values) in enumerate(series):
        stream.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} rg")
        stream.append(f"{legend_x:.2f} {legend_y:.2f} 8.00 3.00 re f")
        pdf_text(stream, legend_x + 11, legend_y - 1, name, size=7)
        legend_x += legend_slot

        points: list[tuple[float, float, float, int]] = []
        for idx, value in enumerate(values):
            if value is None:
                continue
            px = chart_x + (chart_w * idx / max(1, len(values) - 1))
            py = chart_y + ((value - vmin) / (vmax - vmin)) * chart_h
            points.append((px, py, value, idx))
        if len(points) >= 2:
            stream.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} RG 1.4 w")
            p0x, p0y, _p0v, _p0i = points[0]
            stream.append(f"{p0x:.2f} {p0y:.2f} m")
            for px, py, _pv, _pi in points[1:]:
                stream.append(f"{px:.2f} {py:.2f} l")
            stream.append("S")
        for px, py, value, idx in points:
            stream.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} rg")
            stream.append(f"{px - 1.8:.2f} {py - 1.8:.2f} 3.60 3.60 re f")
            if not show_value_labels:
                continue
            seen = printed_at_index.setdefault(idx, set())
            if value in seen:
                continue
            # Desplaza la etiqueta hacia arriba segun cuantos valores
            # distintos ya se han impreso en este mismo punto.
            label_dy = 6 + (len(seen) * 9)
            seen.add(value)
            pdf_text(stream, px - 11, py + label_dy, f"{value:,.0f}".replace(",", "."), size=5.5, color_rgb=color)


def pdf_grouped_bar_chart(
    stream: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    labels: list[str],
    series: list[tuple[str, tuple[float, float, float], list[float | None]]],
    show_value_labels: bool = False,
    stacked: bool = False,
) -> None:
    pdf_rect(stream, x, y, w, h, fill_rgb=(1.0, 1.0, 1.0), stroke_rgb=(0.86, 0.88, 0.92), line_width=0.8)
    pdf_text(stream, x + 8, y + h - 14, title, size=9, bold=True)

    chart_x = x + 34
    chart_y = y + 20
    chart_w = w - 50
    chart_h = h - 60

    numeric = [value for _name, _color, values in series for value in values if value is not None]
    if len(numeric) < 1:
        pdf_text(stream, x + 8, y + 8, "Sin datos", size=8)
        return

    if stacked:
        group_totals = [
            sum((values[i] or 0) for _name, _color, values in series if i < len(values))
            for i in range(len(labels))
        ]
        vmin = 0.0
        vmax = max(group_totals) if group_totals else 1.0
    else:
        vmin = min(0.0, min(numeric))
        vmax = max(numeric)
    if vmax <= vmin:
        vmax = vmin + 1.0
    pad = (vmax - vmin) * 0.08
    vmax += pad

    for idx in range(5):
        gy = chart_y + (chart_h * idx / 4)
        stream.append("0.93 0.94 0.96 RG 0.4 w")
        stream.append(f"{chart_x:.2f} {gy:.2f} m {chart_x + chart_w:.2f} {gy:.2f} l S")

    stream.append("0.60 0.64 0.72 RG 0.7 w")
    stream.append(f"{chart_x:.2f} {chart_y:.2f} m {chart_x:.2f} {chart_y + chart_h:.2f} l S")
    stream.append(f"{chart_x:.2f} {chart_y:.2f} m {chart_x + chart_w:.2f} {chart_y:.2f} l S")

    group_count = max(1, len(labels))
    group_w = chart_w / group_count
    bar_w = max(8.0, min(26.0, group_w - 10)) if stacked else max(4.0, min(16.0, group_w / max(2, len(series) + 1)))

    legend_slot = min(150, (w - 16) / max(1, len(series)))
    legend_x = max(chart_x, x + (w - (len(series) * legend_slot)) / 2)
    legend_y = y + h - 28
    for name, color, _values in series:
        stream.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} rg")
        stream.append(f"{legend_x:.2f} {legend_y:.2f} 8.00 3.00 re f")
        pdf_text(stream, legend_x + 11, legend_y - 1, name, size=7)
        legend_x += legend_slot

    for group_idx, label in enumerate(labels):
        gx = chart_x + group_w * group_idx
        center = gx + (group_w / 2)
        pdf_text(stream, center - 9, chart_y - 12, label, size=6.5)

        if stacked:
            base = chart_y
            for _name, color, values in series:
                if group_idx >= len(values) or values[group_idx] is None:
                    continue
                value = values[group_idx] or 0
                seg_h = ((value - vmin) / (vmax - vmin)) * chart_h
                bx = gx + (group_w - bar_w) / 2
                stream.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} rg")
                stream.append(f"{bx:.2f} {base:.2f} {bar_w:.2f} {seg_h:.2f} re f")
                if show_value_labels and value:
                    pdf_text(stream, bx + (bar_w / 2) - 8, base + seg_h + 2, f"{value:,.0f}".replace(",", "."), size=5.5, color_rgb=color)
                base += seg_h
            if show_value_labels and base > chart_y:
                total = sum((values[group_idx] or 0) for _name, _color, values in series if group_idx < len(values))
                pdf_text(stream, gx + (group_w / 2) - 10, base + 9, f"{total:,.0f}".replace(",", "."), size=6, bold=True)
        else:
            for series_idx, (_name, color, values) in enumerate(series):
                if group_idx >= len(values) or values[group_idx] is None:
                    continue
                value = values[group_idx] or 0
                bar_h = ((value - vmin) / (vmax - vmin)) * chart_h
                bx = gx + 4 + (series_idx * (bar_w + 2))
                stream.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} rg")
                stream.append(f"{bx:.2f} {chart_y:.2f} {bar_w:.2f} {bar_h:.2f} re f")
                if show_value_labels and value:
                    pdf_text(stream, bx + (bar_w / 2) - 6, chart_y + bar_h + 3, f"{value:,.0f}".replace(",", "."), size=6)

    for tick in range(5):
        value = vmin + ((vmax - vmin) * tick / 4)
        py = chart_y + (chart_h * tick / 4)
        pdf_text(stream, x + 2, py - 2, f"{value:,.0f}".replace(",", "."), size=6.5)


def _truncate_to_width(text: str, max_width: float, size: float) -> str:
    """Recorta un texto para que quepa en max_width, evitando que se
    solape con la columna siguiente (aproximacion por ancho medio de
    caracter de Helvetica, suficiente para una tabla informativa)."""
    if not text:
        return text
    avg_char_w = size * 0.55
    max_chars = max(1, int(max_width / avg_char_w))
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def pdf_table(
    stream: list[str],
    x: float,
    y_top: float,
    col_widths: list[float],
    headers: list[str],
    rows: list[list[str]],
    row_height: float = 15.0,
    font_size: float = 7.5,
) -> float:
    """Dibuja una tabla simple empezando en y_top y devuelve la y final."""
    total_w = sum(col_widths)
    header_h = row_height
    pdf_rect(stream, x, y_top - header_h, total_w, header_h, fill_rgb=(0.88, 0.90, 0.93), stroke_rgb=(0.80, 0.83, 0.88))
    cx = x
    for header, cw in zip(headers, col_widths):
        pdf_text(stream, cx + 5, y_top - header_h + 4.5, _truncate_to_width(header, cw - 8, font_size), size=font_size, bold=True)
        cx += cw

    y = y_top - header_h
    for row_idx, row in enumerate(rows):
        y -= row_height
        if row_idx % 2 == 1:
            pdf_rect(stream, x, y, total_w, row_height, fill_rgb=(0.97, 0.97, 0.96), stroke_rgb=None)
        cx = x
        for value, cw in zip(row, col_widths):
            pdf_text(stream, cx + 5, y + 4.5, _truncate_to_width(value, cw - 8, font_size), size=font_size)
            cx += cw
    pdf_rect(stream, x, y, total_w, y_top - header_h - y, fill_rgb=None, stroke_rgb=(0.80, 0.83, 0.88), line_width=0.7)
    return y


def assemble_pdf(pages: list[list[str]], page_size: tuple[float, float] = (PAGE_WIDTH, PAGE_HEIGHT)) -> bytes:
    """Ensambla N paginas (cada una una lista de operadores de content stream) en un PDF valido."""
    if not pages:
        pages = [[]]
    pw, ph = page_size

    font_regular_obj = 3
    font_bold_obj = 4
    first_page_obj = 5  # cada pagina ocupa 2 objetos: Page + Contents

    page_obj_ids = [first_page_obj + (2 * i) for i in range(len(pages))]
    kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]

    for idx, page_ops in enumerate(pages):
        content_obj_id = first_page_obj + (2 * idx) + 1
        stream_bytes = "\n".join(page_ops).encode("latin-1", errors="replace")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.0f} {ph:.0f}] "
                f"/Resources << /Font << /F1 {font_regular_obj} 0 R /F2 {font_bold_obj} 0 R >> >> "
                f"/Contents {content_obj_id} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii") + stream_bytes + b"\nendstream"
        )

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{idx} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)
