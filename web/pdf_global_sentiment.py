"""
Server-side PDF builder for the Global Market Sentiment dashboard.

Renders the dict returned by `global_sentiment.engine.get_global_sentiment()`
to a clean A4 portrait PDF. Layout mirrors the dashboard sections:

  1. Header (timestamp, source, cache age)
  2. Regime banner (RISK-ON / RISK-OFF / NEUTRAL etc.) with rationale + drivers
  3. Composite Score card (-100..+100) with top contributors + bar
  4. Regime stability (consecutive days held, flips)
  5. India impact translator (USD/INR, oil, DXY commentary)
  6. Layman summary points
  7. Indian sector rotation (leaders / laggards / rotation tag)
  8. Correlations matrix (30/60/90d, expectation, holding flag)
  9. Historical context (1Y / 5Y rank for headline indicators)
 10. Money-flow signals
 11. Section-by-section verdicts (bullish / bearish / cautious)
 12. Per-instrument tables grouped by category (equity / fx / commodity / bond / crypto / sector)
 13. Data quality footer (coverage, stale instruments)

ReportLab does all layout — no headless browser, output is deterministic.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ─────────────────────────── palette (light theme) ───────────────────────────

BRAND      = colors.HexColor("#1F4E78")
GREEN      = colors.HexColor("#0E8B3D")
RED        = colors.HexColor("#C0322B")
AMBER      = colors.HexColor("#B7791F")
BLUE       = colors.HexColor("#1F4E78")
PURPLE     = colors.HexColor("#6B2D9C")
CYAN       = colors.HexColor("#0E7490")
GREY_DARK  = colors.HexColor("#1F2933")
GREY       = colors.HexColor("#6B7280")
GREY_LIGHT = colors.HexColor("#E5E7EB")
HEAD_BG    = colors.HexColor("#2E5A8A")
ROW_ALT    = colors.HexColor("#F3F6FA")
GREEN_BG   = colors.HexColor("#E8F5EC")
RED_BG     = colors.HexColor("#FBE0DE")
AMBER_BG   = colors.HexColor("#FFF1C8")
BLUE_BG    = colors.HexColor("#DCEAF7")
PURPLE_BG  = colors.HexColor("#ECDFFA")
GREY_BG    = colors.HexColor("#F0F2F5")


# ─────────────────────────── styles ───────────────────────────

def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title":    ParagraphStyle("Title", parent=base["Title"], fontSize=18,
                                   textColor=BRAND, alignment=0, spaceAfter=2, leading=22),
        "subtitle": ParagraphStyle("Subtitle", parent=base["Normal"], fontSize=9,
                                   textColor=GREY, spaceAfter=10),
        "h2":       ParagraphStyle("H2", parent=base["Heading2"], fontSize=12,
                                   textColor=BRAND, spaceBefore=10, spaceAfter=4, leading=15),
        "h3":       ParagraphStyle("H3", parent=base["Heading3"], fontSize=10,
                                   textColor=BRAND, spaceBefore=6, spaceAfter=3, leading=13),
        "body":     ParagraphStyle("Body", parent=base["Normal"], fontSize=9,
                                   textColor=GREY_DARK, leading=12, spaceAfter=2),
        "small":    ParagraphStyle("Small", parent=base["Normal"], fontSize=8,
                                   textColor=GREY, leading=11),
        "cell":     ParagraphStyle("Cell", parent=base["Normal"], fontSize=8,
                                   textColor=GREY_DARK, leading=10),
        "rec_action": ParagraphStyle("RecAction", parent=base["Normal"], fontSize=22,
                                     fontName="Helvetica-Bold", spaceAfter=4, leading=24),
        "kpi_label": ParagraphStyle("KpiLabel", parent=base["Normal"], fontSize=7.5,
                                    textColor=GREY, leading=10, alignment=1),
        "kpi_value": ParagraphStyle("KpiValue", parent=base["Normal"], fontSize=14,
                                    textColor=GREY_DARK, leading=17, alignment=1,
                                    fontName="Helvetica-Bold"),
        "note":     ParagraphStyle("Note", parent=base["Normal"], fontSize=8,
                                   textColor=GREY_DARK, leading=11, leftIndent=8),
    }


# ─────────────────────────── helpers ───────────────────────────

def _fmt_num(v: Any, decimals: int = 2) -> str:
    if v is None: return "—"
    try:
        return f"{float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v: Any, decimals: int = 2, signed: bool = True) -> str:
    if v is None or not isinstance(v, (int, float)): return "—"
    sign = "+" if (signed and v >= 0) else ""
    return f"{sign}{v:.{decimals}f}%"


def _safe_unit(unit: Any) -> str:
    """ReportLab default Helvetica is Latin-1 only. The Unicode rupee glyph
    renders as a missing-character box (■). Replace it with 'Rs.' so the
    PDF stays readable without bundling a Unicode font."""
    if not unit:
        return ""
    s = str(unit)
    return s.replace("₹", "Rs.").replace("₹", "Rs.")


def _fmt_last(v: Any, unit: Any) -> str:
    """Render a numeric reading with a Latin-1-safe unit suffix/prefix."""
    if v is None:
        return "—"
    if not isinstance(v, (int, float)):
        return str(v)
    u = _safe_unit(unit)
    if u in ("%",):
        return f"{v:,.2f}{u}"
    if u in ("$",):
        return f"${v:,.2f}"
    if u.startswith("Rs."):
        return f"Rs. {v:,.2f}"
    return f"{v:,.2f}"


def _signed_color(v: Any) -> colors.Color:
    if v is None or not isinstance(v, (int, float)):
        return GREY_DARK
    return GREEN if v > 0 else (RED if v < 0 else GREY_DARK)


def _tone_colors(tone: str) -> tuple[colors.Color, colors.Color]:
    """Return (text, background) colours for a verdict tone."""
    t = (tone or "").lower()
    if t in ("bullish", "risk-on", "high-buy"):
        return GREEN, GREEN_BG
    if t in ("bearish", "risk-off", "high-sell"):
        return RED, RED_BG
    if t in ("cautious", "extreme", "high"):
        return AMBER, AMBER_BG
    if t in ("low",):
        return BLUE, BLUE_BG
    if t in ("mixed", "neutral", "normal"):
        return GREY_DARK, GREY_BG
    return GREY_DARK, GREY_BG


def _label_colors(label: str) -> tuple[colors.Color, colors.Color]:
    """Map regime/composite label words to (text, background)."""
    l = (label or "").upper()
    if "STRONG RISK-ON" in l or "RISK-ON" in l:
        return GREEN, GREEN_BG
    if "STRONG RISK-OFF" in l or "RISK-OFF" in l:
        return RED, RED_BG
    if "NEUTRAL" in l or "MIXED" in l or "TRANSITION" in l:
        return AMBER, AMBER_BG
    return GREY_DARK, GREY_BG


def _section_title(text: str, st: dict) -> Table:
    """Section heading rendered as a small table with a coloured left bar
    + light blue background so sections separate visually."""
    p = Paragraph(f"<font color='{BRAND.hexval()}'><b>{text}</b></font>", st["h2"])
    t = Table([[p]], colWidths=["*"])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#EEF4FB")),
        ("LINEBEFORE",   (0, 0), (0, -1), 3, BRAND),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    return t


def _grid_table(headers: list[str], rows: list[list[Any]],
                col_widths: list[float],
                color_cells: list[tuple] | None = None,
                font_size: float = 8.0) -> Table:
    data = [headers] + rows
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), font_size),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("FONTSIZE", (0, 1), (-1, -1), font_size),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        # More generous body padding so wrapped Paragraphs don't clip neighbours
        ("LEFTPADDING",   (0, 1), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 1), (-1, -1), 4),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BFCBD7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, ROW_ALT]),
    ]
    if color_cells:
        style.extend(color_cells)
    tbl.setStyle(TableStyle(style))
    return tbl


def _kpi_card(label: str, value: str, st: dict,
              value_color: colors.Color | None = None,
              fill: colors.Color | None = None) -> Table:
    label_p = Paragraph(label.upper(), st["kpi_label"])
    if value_color is None:
        value_p = Paragraph(value, st["kpi_value"])
    else:
        value_p = Paragraph(
            f"<font color='{value_color.hexval()}'>{value}</font>", st["kpi_value"])
    tbl = Table([[label_p], [value_p]], colWidths=[None])
    accent = value_color or BRAND
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_LIGHT),
        ("BACKGROUND", (0, 0), (-1, -1), fill or colors.HexColor("#F8FAFC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        # Subtle accent line at the top — matches the value colour
        ("LINEABOVE", (0, 0), (-1, 0), 2, accent),
    ]))
    return tbl


def _kpi_row(cards: list[Table], content_w: float) -> Table:
    n = len(cards)
    cw = [content_w / n] * n
    tbl = Table([cards], colWidths=cw)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tbl


def _bullets(items: list[str], st: dict, color: colors.Color = BRAND) -> list:
    out = []
    for s in (items or []):
        if not s: continue
        out.append(Paragraph(
            f"<font color='{color.hexval()}'>•</font> {s}", st["note"]))
    return out


# ─────────────────────────── section builders ───────────────────────────

def _build_header(data: dict, st: dict) -> list:
    fetched_at = data.get("fetched_at")
    cache_age  = data.get("cache_age_seconds")
    health     = data.get("health") or {}
    source     = health.get("source") or "unknown"

    when = ""
    if fetched_at:
        try:
            when = datetime.utcfromtimestamp(int(fetched_at)).strftime("%d %b %Y %H:%M UTC")
        except Exception:
            when = ""

    bits = [f"Generated {when}" if when else "Global market readout"]
    if cache_age is not None:
        bits.append(f"cache age {int(cache_age)}s")
    bits.append(f"source <b>{source}</b>")

    title_block = Table([
        [Paragraph("<b>Global Market Sentiment</b>", st["title"])],
        [Paragraph(
            " &nbsp;&bull;&nbsp; ".join(bits) +
            " &nbsp;&bull;&nbsp; Hiranya Macro Inter-market Engine",
            st["subtitle"],
        )],
    ], colWidths=["*"])
    title_block.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        # Subtle accent rule under the whole title block
        ("LINEBELOW", (0, 1), (-1, 1), 1.5, BRAND),
    ]))
    return [title_block, Spacer(1, 6)]


def _build_regime_banner(data: dict, st: dict, content_w: float) -> list:
    regime = data.get("regime") or {}
    if not regime:
        return []

    label    = regime.get("label", "—")
    emoji    = regime.get("emoji", "")
    rationale = regime.get("rationale", "")
    drivers  = regime.get("drivers") or []

    text_color, bg_color = _label_colors(label)
    action_style = ParagraphStyle(
        "RegimeAction", parent=st["rec_action"], textColor=text_color,
    )

    head = Table(
        [[
            Paragraph(f"{emoji} {label}", action_style),
            Paragraph(
                f"<font color='{GREY.hexval()}'>Rationale:</font> {rationale}",
                st["body"],
            ),
        ]],
        colWidths=[content_w * 0.40, content_w * 0.60],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), bg_color),
        ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 4, text_color),
    ]))

    elems = [_section_title("Regime", st), head]

    if drivers:
        elems.append(Spacer(1, 4))
        elems.append(Paragraph("<b>Top drivers:</b>", st["body"]))
        elems.extend(_bullets(drivers, st, color=text_color))

    return elems


def _build_composite_score(data: dict, st: dict, content_w: float) -> list:
    comp = data.get("composite") or {}
    if not comp:
        return []

    score = comp.get("score")
    label = comp.get("label", "—")
    drivers = comp.get("top_drivers") or []
    text_color, bg_color = _label_colors(label)

    score_str = f"{score:+.1f}" if isinstance(score, (int, float)) else "—"

    elems = [_section_title("Composite Sentiment Score (-100 .. +100)", st)]

    cards = [
        _kpi_card("Score", score_str, st, value_color=text_color, fill=bg_color),
        _kpi_card("Label", label, st, value_color=text_color, fill=bg_color),
        _kpi_card("Calibration", str(comp.get("calibration_source") or "default"),
                  st, value_color=BRAND),
        _kpi_card("Top Drivers", str(len(drivers)), st),
    ]
    elems.append(_kpi_row(cards, content_w))
    elems.append(Spacer(1, 6))

    if drivers:
        rows: list[list[Any]] = []
        color_cells: list[tuple] = []
        for i, d in enumerate(drivers, start=1):
            contrib = d.get("contribution", 0) or 0
            chg5d = d.get("change_5d_pct")
            polarity = d.get("polarity", 0)
            rows.append([
                d.get("name", d.get("key", "—")),
                _fmt_pct(chg5d, decimals=2),
                _fmt_num(contrib, decimals=2),
                "+1 (risk-on)" if polarity == 1 else
                ("-1 (risk-off)" if polarity == -1 else "0 (context)"),
            ])
            color_cells += [
                ("TEXTCOLOR", (1, i), (1, i),
                 GREEN if (chg5d is not None and chg5d >= 0) else RED),
                ("TEXTCOLOR", (2, i), (2, i),
                 GREEN if contrib >= 0 else RED),
                ("FONTNAME", (2, i), (2, i), "Helvetica-Bold"),
                ("ALIGN",     (1, i), (2, i), "RIGHT"),
                ("ALIGN",     (3, i), (3, i), "CENTER"),
            ]

        cw = [content_w * 0.40, content_w * 0.18, content_w * 0.20, content_w * 0.22]
        elems.append(_grid_table(
            ["Instrument", "5d %", "Contribution", "Polarity"], rows, cw, color_cells,
        ))

    return elems


def _build_regime_stability(data: dict, st: dict, content_w: float) -> list:
    stab = data.get("regime_stability") or {}
    if not stab:
        return []
    days = stab.get("days_held")
    flips = stab.get("flips_30d")
    confidence = stab.get("confidence", "unknown")

    conf_text, conf_bg = _tone_colors(
        "bullish" if confidence == "high" else
        "cautious" if confidence == "medium" else
        "bearish" if confidence == "low" else "neutral"
    )

    cards = [
        _kpi_card("Days Held",   str(days)  if days is not None else "—", st),
        _kpi_card("Flips (30d)", str(flips) if flips is not None else "—", st),
        _kpi_card("Confidence", str(confidence).upper(), st,
                  value_color=conf_text, fill=conf_bg),
    ]
    return [_section_title("Regime Stability", st),
            _kpi_row(cards, content_w),
            Spacer(1, 4)]


def _build_india_impact(data: dict, st: dict, content_w: float) -> list:
    india = data.get("india_impact") or {}
    if not india:
        return []
    summary = india.get("summary") or ""
    summary_tone = india.get("summary_tone") or "neutral"
    points = india.get("points") or []

    text_color, bg_color = _tone_colors(summary_tone)

    elems = [_section_title("India Impact", st)]
    if summary:
        # Banner with tone color
        head = Table([[
            Paragraph(
                f"<font color='{text_color.hexval()}'><b>{summary}</b></font>",
                st["body"],
            )
        ]], colWidths=[content_w])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("BACKGROUND", (0, 0), (-1, -1), bg_color),
            ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
            ("LINEBEFORE", (0, 0), (0, -1), 3, text_color),
        ]))
        elems.append(head)
        elems.append(Spacer(1, 4))

    if points:
        for p in points:
            tone = (p.get("tone") if isinstance(p, dict) else None) or "neutral"
            text = (p.get("text") if isinstance(p, dict) else str(p)) or ""
            t_color, _ = _tone_colors(tone)
            elems.append(Paragraph(
                f"<font color='{t_color.hexval()}'>•</font> {text}",
                st["note"],
            ))
    return elems


def _build_layman(data: dict, st: dict, content_w: float) -> list:
    layman = data.get("layman") or {}
    if not layman:
        return []
    elems = [_section_title("Plain-English Summary", st)]
    summary = layman.get("summary") or ""
    if summary:
        elems.append(Paragraph(summary, st["body"]))
        elems.append(Spacer(1, 2))
    points = layman.get("points") or []
    if points:
        for p in points:
            if isinstance(p, dict):
                head = p.get("title") or p.get("headline") or ""
                body = p.get("text") or p.get("body") or ""
                tone = p.get("tone") or "neutral"
                t_color, _ = _tone_colors(tone)
                if head:
                    elems.append(Paragraph(
                        f"<font color='{t_color.hexval()}'><b>{head}</b></font>", st["body"]))
                if body:
                    elems.append(Paragraph(body, st["note"]))
            else:
                elems.append(Paragraph(f"• {p}", st["note"]))
    return elems


def _build_sectors(data: dict, st: dict, content_w: float) -> list:
    sectors = data.get("sectors") or {}
    if not sectors:
        return []
    leaders  = sectors.get("leaders") or []
    laggards = sectors.get("laggards") or []
    rotation = sectors.get("rotation") or ""
    avg_comp = sectors.get("avg_composite")

    elems = [_section_title("Indian Sector Rotation", st)]

    if rotation:
        rot_lower = rotation.lower()
        if "broad strength" in rot_lower:
            tcol, bg = GREEN, GREEN_BG
        elif "broad weakness" in rot_lower:
            tcol, bg = RED, RED_BG
        elif "rotation" in rot_lower:
            tcol, bg = AMBER, AMBER_BG
        else:
            tcol, bg = GREY_DARK, GREY_BG

        head_text = (f"<b>{rotation}</b>"
                     + (f" &nbsp;·&nbsp; avg composite "
                        f"<font color='{_signed_color(avg_comp).hexval()}'>"
                        f"{_fmt_num(avg_comp, decimals=2)}</font>"
                        if avg_comp is not None else ""))
        head = Table([[Paragraph(head_text, st["body"])]], colWidths=[content_w])
        head.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
            ("LINEBEFORE", (0, 0), (0, -1), 3, tcol),
        ]))
        elems.append(head)
        elems.append(Spacer(1, 4))

    def _sector_table(title: str, rows_in: list[dict],
                      header_color: colors.Color) -> list:
        if not rows_in:
            return []
        rows: list[list[Any]] = []
        color_cells: list[tuple] = []
        for i, r in enumerate(rows_in, start=1):
            ch1d  = r.get("change_1d_pct")
            ch5d  = r.get("change_5d_pct")
            ch20d = r.get("change_20d_pct")
            comp  = r.get("composite")
            rows.append([
                r.get("name", "—"),
                _fmt_pct(ch1d), _fmt_pct(ch5d), _fmt_pct(ch20d),
                _fmt_num(comp, decimals=2),
            ])
            color_cells += [
                ("TEXTCOLOR", (1, i), (1, i), _signed_color(ch1d)),
                ("TEXTCOLOR", (2, i), (2, i), _signed_color(ch5d)),
                ("TEXTCOLOR", (3, i), (3, i), _signed_color(ch20d)),
                ("TEXTCOLOR", (4, i), (4, i), _signed_color(comp)),
                ("FONTNAME",  (4, i), (4, i), "Helvetica-Bold"),
                ("ALIGN",     (1, i), (4, i), "RIGHT"),
            ]
        cw = [content_w * 0.40, content_w * 0.13, content_w * 0.13,
              content_w * 0.14, content_w * 0.20]
        return [
            Paragraph(f"<b><font color='{header_color.hexval()}'>{title}</font></b>",
                      st["body"]),
            _grid_table(["Sector", "1d %", "5d %", "20d %", "Composite"],
                        rows, cw, color_cells),
            Spacer(1, 4),
        ]

    elems.extend(_sector_table("Leaders",  leaders,  GREEN))
    elems.extend(_sector_table("Laggards", laggards, RED))
    return elems


def _build_correlations(data: dict, st: dict, content_w: float) -> list:
    corrs = data.get("correlations") or []
    if not corrs:
        return []

    headers = ["Pair", "30d", "60d", "90d", "Expectation",
               "Magnitude", "Holding", "Stability"]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    # Cell-level styles so wrapped Paragraphs match the surrounding font
    cell_style = ParagraphStyle(
        "CorrCell", fontSize=7.5, leading=9.5, textColor=GREY_DARK,
    )
    pair_style = ParagraphStyle(
        "CorrPair", fontSize=7.5, leading=9.5, textColor=GREY_DARK,
        fontName="Helvetica-Bold",
    )

    for i, c in enumerate(corrs, start=1):
        c30 = c.get("corr_30d") if c.get("corr_30d") is not None else c.get("correlation")
        c60 = c.get("corr_60d")
        c90 = c.get("corr_90d")
        holding = c.get("holding")
        stab = c.get("stability") or "—"
        magn = c.get("magnitude") or "—"
        rs = c.get("regime_shift")

        rows.append([
            Paragraph(c.get("pair", "—"), pair_style),
            _fmt_num(c30, decimals=2),
            _fmt_num(c60, decimals=2),
            _fmt_num(c90, decimals=2),
            Paragraph(c.get("expectation", "—"), cell_style),
            magn.upper(),
            "✓ HOLDING" if holding else "✗ BROKEN",
            stab.upper() + (" * FLIP" if rs else ""),
        ])
        # Colour the headline 30d cell by sign
        if c30 is not None:
            color_cells.append(("TEXTCOLOR", (1, i), (1, i),
                                GREEN if c30 > 0 else (RED if c30 < 0 else GREY_DARK)))
            color_cells.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
        # Holding / stability column tints
        color_cells.append((
            "TEXTCOLOR", (6, i), (6, i),
            GREEN if holding else RED,
        ))
        if stab.lower() == "stable":
            color_cells.append(("TEXTCOLOR", (7, i), (7, i), GREEN))
        elif stab.lower() == "shifting":
            color_cells.append(("TEXTCOLOR", (7, i), (7, i), AMBER))
        elif stab.lower() == "weak":
            color_cells.append(("TEXTCOLOR", (7, i), (7, i), RED))
        if rs:
            color_cells.append(("BACKGROUND", (7, i), (7, i), AMBER_BG))
        for ci in (1, 2, 3, 5, 6, 7):
            color_cells.append(("ALIGN", (ci, i), (ci, i), "CENTER"))
        # Top-align cells so wrapped multi-line text doesn't push numbers to the bottom
        color_cells.append(("VALIGN", (0, i), (-1, i), "TOP"))

    # Wider Pair + Expectation columns, narrower correlation numerics, narrower trailing tags.
    cw = [
        content_w * 0.16,  # Pair
        content_w * 0.07, content_w * 0.07, content_w * 0.07,  # 30/60/90 d
        content_w * 0.31,  # Expectation (was 0.30 — slight bump)
        content_w * 0.10,  # Magnitude
        content_w * 0.11,  # Holding (slightly wider so "✓ HOLDING" sits comfortably)
        content_w * 0.11,  # Stability
    ]
    return [
        _section_title("Inter-market Correlations (3-window)", st),
        Paragraph(
            "Pairwise rolling correlations (Pearson) over 30 / 60 / 90 days. "
            "Headline column is 30d. 'Stability' shows agreement across windows; "
            "'* FLIP' marks a recent regime change between 30d and 90d.",
            st["small"],
        ),
        Spacer(1, 3),
        _grid_table(headers, rows, cw, color_cells, font_size=7.5),
    ]


def _build_historical_context(data: dict, st: dict, content_w: float) -> list:
    ctx = data.get("historical_context") or []
    if not ctx:
        return []

    headers = ["Indicator", "Last", "1Y rank", "5Y rank", "Position", "Multi-year note"]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    cell_style = ParagraphStyle(
        "HCNote", fontSize=8, leading=10, textColor=GREY_DARK,
    )

    for i, c in enumerate(ctx, start=1):
        last = c.get("last")
        unit = c.get("unit") or ""
        last_str = _fmt_last(last, unit)
        rank1y = c.get("pct_rank_1y")
        rank5y = c.get("pct_rank_5y")
        label  = c.get("label", "—")
        note   = c.get("context_note") or ""
        tone   = c.get("tone") or "neutral"

        t_color, t_bg = _tone_colors(tone)
        # Position cell as Paragraph so it can wrap & carry colour
        pos_style = ParagraphStyle(
            f"HCPos{i}", fontSize=8, leading=10, textColor=t_color,
            fontName="Helvetica-Bold",
        )

        rows.append([
            c.get("name", c.get("key", "—")),
            last_str,
            _fmt_num(rank1y, decimals=0) if rank1y is not None else "—",
            _fmt_num(rank5y, decimals=0) if rank5y is not None else "—",
            Paragraph(label, pos_style),
            Paragraph(note, cell_style) if note else "",
        ])
        if tone == "extreme":
            color_cells.append(("BACKGROUND", (4, i), (4, i), t_bg))
        for ci in (1, 2, 3):
            color_cells.append(("ALIGN", (ci, i), (ci, i), "RIGHT" if ci == 1 else "CENTER"))
        color_cells.append(("VALIGN", (0, i), (-1, i), "TOP"))

    # Bigger Last column (Rs. prefix needs space), bigger Multi-year note column.
    cw = [
        content_w * 0.18,  # Indicator
        content_w * 0.14,  # Last (Rs. + 2 decimals)
        content_w * 0.09,  # 1Y rank
        content_w * 0.09,  # 5Y rank
        content_w * 0.18,  # Position label
        content_w * 0.32,  # Multi-year note
    ]
    return [
        _section_title("Historical Context (1Y vs 5Y)", st),
        _grid_table(headers, rows, cw, color_cells, font_size=8),
    ]


def _build_money_flow(data: dict, st: dict, content_w: float) -> list:
    flows = data.get("money_flow") or []
    if not flows:
        return []
    elems = [_section_title("Money-Flow Signals", st)]
    for f in flows:
        if isinstance(f, dict):
            tone = f.get("tone") or f.get("direction") or "neutral"
            text = f.get("text") or f.get("summary") or ""
            head = f.get("title") or ""
            t_color, t_bg = _tone_colors(tone)
            head_html = (f"<b>{head}</b> — " if head else "") + text
            row = Table([[Paragraph(
                f"<font color='{t_color.hexval()}'>•</font> {head_html}",
                st["note"])]], colWidths=[content_w])
            row.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), t_bg),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",(0, 0), (-1, -1), 6),
                ("TOPPADDING",  (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ("LINEBEFORE",  (0, 0), (0, -1), 2, t_color),
            ]))
            elems.append(row)
            elems.append(Spacer(1, 2))
        else:
            elems.append(Paragraph(f"• {f}", st["note"]))
    return elems


def _build_section_verdicts(data: dict, st: dict, content_w: float) -> list:
    sv = data.get("section_verdicts") or {}
    if not sv:
        return []
    elems = [_section_title("Section-by-Section Verdicts", st)]
    for name, v in sv.items():
        if not isinstance(v, dict): continue
        tone = v.get("tone") or "neutral"
        head = v.get("headline") or ""
        body = v.get("body") or ""
        obs  = v.get("observations") or []
        t_color, t_bg = _tone_colors(tone)

        title = name.replace("_", " ").title()
        head_text = (f"<b>{title}</b> — "
                     f"<font color='{t_color.hexval()}'><b>{head}</b></font>")
        elems.append(Paragraph(head_text, st["body"]))
        if body:
            row = Table([[Paragraph(body, st["note"])]], colWidths=[content_w])
            row.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), t_bg),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",(0, 0), (-1, -1), 6),
                ("TOPPADDING",  (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
                ("LINEBEFORE",  (0, 0), (0, -1), 2, t_color),
            ]))
            elems.append(row)
        for o in obs:
            elems.append(Paragraph(f"&nbsp;&nbsp;◦ {o}", st["small"]))
        elems.append(Spacer(1, 3))
    return elems


def _build_instruments(data: dict, st: dict, content_w: float) -> list:
    cats = data.get("instruments") or {}
    if not cats:
        return []

    cat_order = [
        ("equity",    "Equities (Risk-On Indicator)"),
        ("bond",      "Bonds & Volatility"),
        ("fx",        "Currencies"),
        ("commodity", "Commodities"),
        ("crypto",    "Crypto"),
        ("sector",    "Sector ETFs"),
    ]

    elems: list = [_section_title("Per-Instrument Snapshot", st)]
    for cat_key, cat_label in cat_order:
        items = cats.get(cat_key) or []
        if not items: continue
        elems.append(Paragraph(f"<b>{cat_label}</b>", st["h3"]))
        headers = ["Instrument", "Last", "1d %", "5d %", "20d %", "60d %",
                   "1Y rank", "Vol %", "Status"]
        rows: list[list[Any]] = []
        color_cells: list[tuple] = []
        for i, r in enumerate(items, start=1):
            unit = r.get("unit") or ""
            last = r.get("last")
            last_str = _fmt_last(last, unit)
            ch1, ch5, ch20, ch60 = (
                r.get("change_1d_pct"), r.get("change_5d_pct"),
                r.get("change_20d_pct"), r.get("change_60d_pct"),
            )
            rank = r.get("pct_rank_1y")
            vol  = r.get("realized_vol_pct")
            stale = r.get("is_stale")
            rows.append([
                r.get("name", "—"),
                last_str,
                _fmt_pct(ch1),
                _fmt_pct(ch5),
                _fmt_pct(ch20),
                _fmt_pct(ch60),
                f"{int(rank)}" if isinstance(rank, (int, float)) else "—",
                f"{vol:.1f}" if isinstance(vol, (int, float)) else "—",
                "STALE" if stale else "FRESH",
            ])
            for ci, val in zip((2, 3, 4, 5), (ch1, ch5, ch20, ch60)):
                color_cells.append(("TEXTCOLOR", (ci, i), (ci, i), _signed_color(val)))
            # Bold the 5d as the headline column
            color_cells.append(("FONTNAME", (3, i), (3, i), "Helvetica-Bold"))
            # Status colouring
            color_cells.append((
                "TEXTCOLOR", (8, i), (8, i),
                AMBER if stale else GREEN,
            ))
            for ci in (1, 2, 3, 4, 5, 6, 7):
                color_cells.append(("ALIGN", (ci, i), (ci, i),
                                    "RIGHT" if ci > 1 else "LEFT"))
            color_cells.append(("ALIGN", (8, i), (8, i), "CENTER"))

        cw = [
            content_w * 0.18,  # Instrument
            content_w * 0.16,  # Last (with Rs. prefix needs more room)
            content_w * 0.085, content_w * 0.085,
            content_w * 0.085, content_w * 0.085,
            content_w * 0.085,  # 1Y rank
            content_w * 0.085,  # Vol
            content_w * 0.115,  # Status
        ]
        elems.append(_grid_table(headers, rows, cw, color_cells, font_size=7.5))
        elems.append(Spacer(1, 4))
    return elems


def _build_data_quality(data: dict, st: dict, content_w: float) -> list:
    dq = data.get("data_quality") or {}
    if not dq:
        return []

    label = dq.get("label", "—")
    coverage = dq.get("coverage_pct")
    loaded = dq.get("instruments_loaded")
    total  = dq.get("instruments_total")
    rejects = dq.get("outlier_rejects")
    stale_list = dq.get("stale_instruments") or []
    source = dq.get("source") or "unknown"

    if "DEGRADED" in label.upper():
        tcol, bg = RED, RED_BG
    elif "PARTIAL" in label.upper() or "STALE" in label.upper():
        tcol, bg = AMBER, AMBER_BG
    else:
        tcol, bg = GREEN, GREEN_BG

    head = Table([[Paragraph(
        f"<b><font color='{tcol.hexval()}'>{label}</font></b> &nbsp;·&nbsp; "
        f"coverage <b>{coverage}%</b> ({loaded}/{total} instruments) &nbsp;·&nbsp; "
        f"outlier rejects <b>{rejects}</b> &nbsp;·&nbsp; source <b>{source}</b>",
        st["body"])]], colWidths=[content_w])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LINEBEFORE",  (0, 0), (0, -1), 3, tcol),
    ]))

    elems = [_section_title("Data Quality", st), head]
    if stale_list:
        elems.append(Spacer(1, 4))
        rows = [[s.get("name", s.get("key", "—")),
                 s.get("ts_last", "—"),
                 f"{s.get('cal_days_stale', '?')}d"]
                for s in stale_list]
        elems.append(_grid_table(
            ["Stale Instrument", "Last Bar", "Days Stale"], rows,
            [content_w * 0.50, content_w * 0.30, content_w * 0.20],
            font_size=8,
        ))
    return elems


# ─────────────────────────── footer ───────────────────────────

def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    page_num = canvas.getPageNumber()
    canvas.drawRightString(
        A4[0] - 12 * mm, 8 * mm,
        f"Page {page_num} • Hiranya Global Sentiment",
    )
    canvas.drawString(
        12 * mm, 8 * mm,
        f"Generated {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')} • "
        f"For informational use only — not financial advice",
    )
    canvas.restoreState()


# ─────────────────────────── public entry ───────────────────────────

def build_global_sentiment_pdf(data: dict) -> bytes:
    """Render the global-sentiment dict to a PDF and return raw bytes.

    `data` is the dict returned by `global_sentiment.engine.get_global_sentiment()`.
    Handles the `ok=False` error case gracefully — surfaces the error message
    on a single page rather than failing.
    """
    data = data or {}

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=14 * mm,
        title="Hiranya — Global Market Sentiment",
        author="Hiranya Macro Inter-market Engine",
    )
    content_w = A4[0] - 24 * mm
    st = _styles()
    story: list = []

    story.extend(_build_header(data, st))

    # Error path
    if not data.get("ok", True) or data.get("error"):
        story.append(Paragraph(
            f"<b>Could not produce global sentiment readout:</b> {data.get('error') or 'unknown error'}",
            st["body"],
        ))
        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
        return buf.getvalue()

    sections = [
        _build_regime_banner,
        _build_composite_score,
        _build_regime_stability,
        _build_india_impact,
        _build_layman,
        _build_sectors,
        _build_section_verdicts,
        _build_correlations,
        _build_historical_context,
        _build_money_flow,
        _build_instruments,
        _build_data_quality,
    ]

    for builder in sections:
        try:
            elems = builder(data, st, content_w)
        except Exception as exc:  # don't let one section take down the whole PDF
            elems = [Paragraph(
                f"<i>Section render error in {builder.__name__}: {exc}</i>",
                st["small"],
            )]
        if elems:
            story.extend(elems)
            story.append(Spacer(1, 6))

    # Closing disclaimer
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Disclaimer:</b> Generated from publicly-available market data. "
        "Inter-market signals are decision aids, not predictions. Use as a "
        "macro overlay alongside per-stock analysis; do not size positions "
        "purely from this readout.",
        st["small"],
    ))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
