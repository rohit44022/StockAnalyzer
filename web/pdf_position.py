"""
Server-side PDF builder for the Position Analysis screen.

Produces a clean, paginated A4 portrait PDF from the dict returned by
`bb_squeeze.portfolio_analyzer.analyze_position(...)`. ReportLab does all
layout — no html2canvas, no headless browser — so output is reliable.

Sections (each with page-break-avoid where it makes sense):
  1. Header — ticker, strategy, date
  2. Recommendation banner
  3. Holding summary (P&L)
  4. Target prices
  5. Current technical indicators
  6. Method I (Squeeze) summary
  7. Buying strategy — current status
  8. All strategies (M2 / M3 / M4)
  9. Multi-system synthesis (Triple, Wyckoff, Dalton, Price Action)
 10. Vince risk & money management
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

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

# ── Palette (light theme — PDFs print best on white) ─────────────
BRAND      = colors.HexColor("#1F4E78")   # blue title
GREEN      = colors.HexColor("#0E8B3D")
RED        = colors.HexColor("#C0322B")
AMBER      = colors.HexColor("#B7791F")
GREY_DARK  = colors.HexColor("#1F2933")
GREY       = colors.HexColor("#6B7280")
GREY_LIGHT = colors.HexColor("#E5E7EB")
HEAD_BG    = colors.HexColor("#2E5A8A")
ROW_ALT    = colors.HexColor("#F3F6FA")


# ─────────────────────────────────────────────────────────────────
#  Styles
# ─────────────────────────────────────────────────────────────────

def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Title"], fontSize=18,
            textColor=BRAND, alignment=0, spaceAfter=2, leading=22,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=9,
            textColor=GREY, spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontSize=12,
            textColor=BRAND, spaceBefore=10, spaceAfter=4, leading=15,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=9,
            textColor=GREY_DARK, leading=12, spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"], fontSize=8,
            textColor=GREY, leading=11,
        ),
        "kv_label": ParagraphStyle(
            "KvLabel", parent=base["Normal"], fontSize=8,
            textColor=GREY, leading=10,
        ),
        "kv_value": ParagraphStyle(
            "KvValue", parent=base["Normal"], fontSize=10,
            textColor=GREY_DARK, leading=12,
            fontName="Helvetica-Bold",
        ),
        "rec_action": ParagraphStyle(
            "RecAction", parent=base["Normal"], fontSize=22,
            fontName="Helvetica-Bold", spaceAfter=4, leading=24,
        ),
        "reason": ParagraphStyle(
            "Reason", parent=base["Normal"], fontSize=9,
            textColor=GREY_DARK, leading=12, leftIndent=10,
            spaceAfter=2,
        ),
    }


# ─────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────

def _fmt(v: Any, fmt: str = "{:,.2f}", default: str = "—") -> str:
    if v is None:
        return default
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        try:
            return fmt.format(v)
        except (ValueError, TypeError):
            return str(v)
    return str(v)


def _money(v: Any) -> str:
    """Format as INR. Uses 'Rs.' prefix because ReportLab's default
    Helvetica is Latin-1 only and renders the Unicode ₹ as a tofu box."""
    if v is None or not isinstance(v, (int, float)):
        return "—"
    return f"Rs. {v:,.2f}"


def _pct(v: Any) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "—"
    return f"{v:+.2f}%"


def _action_color(action: str) -> colors.Color:
    a = (action or "").upper()
    if "SELL" in a:
        return RED
    if "BUY" in a or "ADD" in a:
        return GREEN
    if "HOLD" in a:
        return AMBER
    return GREY_DARK


def _section_title(text: str, st: dict) -> Paragraph:
    return Paragraph(text, st["h2"])


def _kv_table(rows: list[tuple[str, str]], col_widths: tuple[float, float], st: dict) -> Table:
    """Two-column key/value list rendered as a table."""
    data = []
    for label, value in rows:
        data.append([
            Paragraph(label, st["kv_label"]),
            Paragraph(value, st["kv_value"]),
        ])
    tbl = Table(data, colWidths=col_widths, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


def _grid_table(headers: list[str], rows: list[list[str]],
                col_widths: list[float], color_cells: list[tuple] | None = None) -> Table:
    """A compact data table with a colored header band."""
    data = [headers] + rows
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BFCBD7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, ROW_ALT]),
    ]
    if color_cells:
        style.extend(color_cells)
    tbl.setStyle(TableStyle(style))
    return tbl


# ─────────────────────────────────────────────────────────────────
#  Section builders
# ─────────────────────────────────────────────────────────────────

def _build_header(analysis: dict, st: dict, content_w: float) -> list:
    pos = analysis.get("position", {}) or {}
    ticker = pos.get("ticker", "—")
    strat = pos.get("strategy_code", "—")
    buy_date = pos.get("buy_date", "—")
    qty = pos.get("quantity", "—")
    return [
        Paragraph(f"Position Analysis — {ticker}", st["title"]),
        Paragraph(
            f"Generated {date.today().strftime('%d %b %Y')} &nbsp;&bull;&nbsp; "
            f"Strategy <b>{strat}</b> &nbsp;&bull;&nbsp; "
            f"Bought {buy_date} &nbsp;&bull;&nbsp; "
            f"Quantity {qty}",
            st["subtitle"],
        ),
    ]


def _build_recommendation(analysis: dict, st: dict, content_w: float) -> list:
    rec = analysis.get("recommendation") or {}
    if not rec:
        return []

    action = (rec.get("action") or "—").upper()
    strength = rec.get("strength") or "—"
    explain = rec.get("explanation") or rec.get("explain") or ""
    reasons = rec.get("reasons") or []
    warnings = rec.get("warnings") or []
    triggers = rec.get("action_triggers") or []
    confirms = rec.get("confirms") or []

    a_color = _action_color(action)
    action_para_style = ParagraphStyle(
        "RecActionDyn", parent=st["rec_action"],
        textColor=a_color,
    )

    elems: list = [_section_title("Recommendation", st)]

    head_table = Table(
        [[
            Paragraph(action, action_para_style),
            Paragraph(
                f"<font color='{GREY.hexval()}'>Strength:</font> "
                f"<b>{strength}</b><br/>"
                f"<font color='{GREY.hexval()}'>Strategy:</font> "
                f"<b>{rec.get('strategy_code') or analysis.get('position', {}).get('strategy_code', '—')}</b>",
                st["body"],
            ),
        ]],
        colWidths=[content_w * 0.45, content_w * 0.55],
    )
    head_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, a_color),
    ]))
    elems.append(head_table)
    elems.append(Spacer(1, 4))

    if explain:
        elems.append(Paragraph(explain, st["body"]))
        elems.append(Spacer(1, 2))

    def _bullets(label: str, items: list[str], color: colors.Color) -> list:
        if not items:
            return []
        out = [Paragraph(f"<b>{label}</b>", st["body"])]
        for s in items:
            out.append(Paragraph(
                f"<font color='{color.hexval()}'>•</font> {s}", st["reason"]))
        out.append(Spacer(1, 2))
        return out

    elems.extend(_bullets("Reasons",         reasons,  BRAND))
    elems.extend(_bullets("Warnings",        warnings, RED))
    elems.extend(_bullets("Action Triggers", triggers, AMBER))
    elems.extend(_bullets("Confirmations",   confirms, GREEN))

    return [KeepTogether(elems[:2]), *elems[2:]]


def _build_holding(analysis: dict, st: dict, content_w: float) -> list:
    h = analysis.get("holding") or {}
    if not h:
        return []
    pnl = h.get("pnl_amount")
    pnlp = h.get("pnl_pct")
    pnl_color = GREEN if isinstance(pnl, (int, float)) and pnl > 0 else (
        RED if isinstance(pnl, (int, float)) and pnl < 0 else GREY_DARK
    )

    rows = [
        ["Buy Price", _money(h.get("buy_price")),
         "Current Price", _money(h.get("current_price"))],
        ["Quantity", _fmt(h.get("quantity"), "{:,}"),
         "Holding Days", _fmt(h.get("days"), "{:,} d")],
        ["Invested", _money(h.get("invested")),
         "Current Value", _money(h.get("current_value"))],
        [
            Paragraph("<b>P&amp;L (Rs.)</b>", st["kv_label"]),
            Paragraph(
                f"<font color='{pnl_color.hexval()}'><b>{_money(pnl)}</b></font>",
                st["body"],
            ),
            Paragraph("<b>P&amp;L (%)</b>", st["kv_label"]),
            Paragraph(
                f"<font color='{pnl_color.hexval()}'><b>{_pct(pnlp)}</b></font>",
                st["body"],
            ),
        ],
    ]

    cw = content_w / 4
    tbl = Table(rows, colWidths=[cw] * 4)
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_LIGHT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [KeepTogether([_section_title("Holding Summary", st), tbl])]


def _build_targets(analysis: dict, st: dict, content_w: float) -> list:
    t = analysis.get("targets") or {}
    if not t:
        return []
    rows = [
        ["Stop Loss",       _money(t.get("stop_loss")),     "—"],
        ["BB Lower",        _money(t.get("bb_lower")),      _pct(t.get("pct_to_lower"))],
        ["BB Mid",          _money(t.get("bb_mid")),        _pct(t.get("pct_to_mid"))],
        ["+1 σ Target",     _money(t.get("target_1_sigma")),"—"],
        ["BB Upper (+2 σ)", _money(t.get("target_2_sigma")),_pct(t.get("pct_to_upper"))],
        ["+3 σ Target",     _money(t.get("target_3_sigma")),_pct(t.get("pct_to_3sigma"))],
        ["52W High",        _money(t.get("high_52w")),      _pct(t.get("pct_to_52w_high"))],
        ["52W Low",         _money(t.get("low_52w")),       "—"],
        ["Risk : Reward",   _fmt(t.get("risk_reward"), "{:.2f}"), "—"],
    ]
    cw = [content_w * 0.45, content_w * 0.30, content_w * 0.25]
    tbl = _grid_table(["Level", "Price", "Distance"], rows, cw)
    return [KeepTogether([_section_title("Target Prices", st), tbl])]


def _build_indicators(analysis: dict, st: dict, content_w: float) -> list:
    ind = analysis.get("indicators") or {}
    if not ind:
        return []
    rows = [
        ["Price",      _money(ind.get("price")),
         "%b",         _fmt(ind.get("percent_b"), "{:.4f}")],
        ["MFI (14)",   _fmt(ind.get("mfi"), "{:.2f}"),
         "CMF (20)",   _fmt(ind.get("cmf"), "{:.4f}")],
        ["BB Width",   _fmt(ind.get("bbw"), "{:.6f}"),
         "SAR",        _money(ind.get("sar"))],
        ["SAR Bullish", _fmt(ind.get("sar_bull")),
         "Squeeze",   "ON" if ind.get("squeeze_on") else "OFF"],
        ["Volume",     _fmt(ind.get("volume"), "{:,}"),
         "Vol SMA-50", _fmt(ind.get("vol_sma50"), "{:,}")],
    ]
    cw = content_w / 4
    tbl = Table(rows, colWidths=[cw] * 4)
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_LIGHT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), GREY),
        ("TEXTCOLOR", (2, 0), (2, -1), GREY),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [KeepTogether([_section_title("Current Technical Indicators (Daily)", st), tbl])]


def _build_method1(analysis: dict, st: dict, content_w: float) -> list:
    m1 = analysis.get("method1_summary") or {}
    if not m1:
        return []
    sig = "BUY" if m1.get("buy") else "SELL" if m1.get("sell") else (
        "HOLD" if m1.get("hold") else "WAIT" if m1.get("wait") else "—"
    )
    rows = [
        ["Signal",      sig,
         "Confidence",  _fmt(m1.get("confidence"), "{:.0f}%")],
        ["Phase",       str(m1.get("phase") or "—"),
         "Head Fake",   _fmt(m1.get("head_fake"))],
        ["Exit (SAR)",  _fmt(m1.get("exit_sar")),
         "Exit (Lower band)", _fmt(m1.get("exit_lower"))],
        ["Exit (Double-)", _fmt(m1.get("exit_double")),
         "", ""],
    ]
    cw = content_w / 4
    tbl = Table(rows, colWidths=[cw] * 4)
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_LIGHT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), GREY),
        ("TEXTCOLOR", (2, 0), (2, -1), GREY),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [KeepTogether([_section_title("Method I — Squeeze Summary", st), tbl])]


def _build_buying_strategy_current(analysis: dict, st: dict, content_w: float) -> list:
    b = analysis.get("buying_strategy_current") or {}
    if not b:
        return []
    sig = (b.get("signal_type") or "—").upper()
    rows = [
        ["Strategy", f"{b.get('code', '—')} — {b.get('name', '—')}"],
        ["Signal", sig],
        ["Strength", b.get("strength") or "—"],
        ["Confidence", _fmt(b.get("confidence"), "{:.0f}%")],
        ["Reason", b.get("reason") or "—"],
    ]
    label_w = content_w * 0.25
    val_w = content_w - label_w
    data = [[Paragraph(k, st["kv_label"]), Paragraph(str(v), st["body"])] for k, v in rows]
    tbl = Table(data, colWidths=[label_w, val_w])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [KeepTogether([
        _section_title("Buying Strategy — Current Status", st),
        tbl,
    ])]


def _build_all_strategies(analysis: dict, st: dict, content_w: float) -> list:
    strats = analysis.get("all_strategies") or []
    if not strats:
        return []
    headers = ["Code", "Name", "Signal", "Strength", "Conf.", "Reason"]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    for i, s in enumerate(strats, start=1):
        code = s.get("code", "—")
        name = s.get("name", "—")
        sig = (s.get("signal_type") or "—").upper()
        strength = s.get("strength", "—")
        conf = _fmt(s.get("confidence"), "{:.0f}%")
        reason = Paragraph(s.get("reason") or "—", st["small"])
        rows.append([code, name, sig, strength, conf, reason])
        c = _action_color(sig)
        color_cells.append(("TEXTCOLOR", (2, i), (2, i), c))
        color_cells.append(("FONTNAME",  (2, i), (2, i), "Helvetica-Bold"))

    cw = [
        content_w * 0.07, content_w * 0.30, content_w * 0.10,
        content_w * 0.13, content_w * 0.08, content_w * 0.32,
    ]
    tbl = _grid_table(headers, rows, cw, color_cells)
    return [_section_title("All Strategies — Current Signals", st), tbl]


def _build_multi_system(analysis: dict, st: dict, content_w: float) -> list:
    ms = analysis.get("multi_system") or {}
    if not ms:
        return []
    elems: list = [_section_title("Multi-System Synthesis", st)]

    triple = ms.get("triple") or {}
    if triple:
        elems.append(_kv_table([
            ("Triple Verdict", f"<b>{triple.get('verdict', '—')}</b> &nbsp; "
                               f"score {_fmt(triple.get('score'))} / {triple.get('max_score', 425)} &nbsp; "
                               f"conf {_fmt(triple.get('confidence'), '{:.0f}%')}"),
            ("BB / TA / PA", f"BB {_fmt(triple.get('bb_score'))} &nbsp; "
                             f"TA {_fmt(triple.get('ta_score'))} &nbsp; "
                             f"PA {_fmt(triple.get('pa_score'))}"),
            ("Cross-Validation", triple.get("alignment", "—")),
        ], (content_w * 0.32, content_w * 0.68), st))
        elems.append(Spacer(1, 4))

    wk = ms.get("wyckoff") or {}
    if wk:
        elems.append(_kv_table([
            ("Wyckoff Phase",  f"{wk.get('phase', '—')} ({wk.get('sub_phase', '—')})"),
            ("Bias / Bonus",   f"{wk.get('bias', '—')}, bonus {_fmt(wk.get('bonus'))}"),
            ("Confidence",     _fmt(wk.get('confidence'), "{:.0f}%")),
            ("Summary",        wk.get("summary") or "—"),
        ], (content_w * 0.32, content_w * 0.68), st))
        elems.append(Spacer(1, 4))

    pa = ms.get("price_action") or {}
    if pa:
        elems.append(_kv_table([
            ("PA Signal",  f"{pa.get('signal', '—')} / {pa.get('setup', '—')}"),
            ("Strength",   f"{pa.get('strength', '—')} (conf {_fmt(pa.get('confidence'), '{:.0f}%')})"),
            ("Trend / Always-In", f"{pa.get('trend', '—')} / {pa.get('always_in', '—')}"),
            ("PA Score",   _fmt(pa.get("pa_score"))),
            ("PA Stop",    _money(pa.get("stop_loss"))),
        ], (content_w * 0.32, content_w * 0.68), st))
        elems.append(Spacer(1, 4))

    dl = ms.get("dalton") or {}
    if dl:
        va = dl.get("value_area") or {}
        dt = dl.get("day_type") or {}
        elems.append(_kv_table([
            ("Dalton Day Type",   dt.get("type", "—") if isinstance(dt, dict) else str(dt)),
            ("Open Type",         dl.get("open_type", "—")),
            ("Value Area",        f"VAL {_fmt(va.get('val'))} – POC {_fmt(va.get('poc'))} – VAH {_fmt(va.get('vah'))}" if va else "—"),
            ("Profile / Activity", f"{dl.get('profile_shape', '—')} / {dl.get('activity', '—')}"),
            ("POC Migration",     dl.get("poc_migration", "—")),
            ("Summary",           dl.get("summary") or "—"),
        ], (content_w * 0.32, content_w * 0.68), st))

    return elems


def _build_vince_risk(analysis: dict, st: dict, content_w: float) -> list:
    v = analysis.get("vince_risk") or {}
    if not v or v.get("error"):
        # Show the error gracefully if the section ran but failed
        if v.get("error"):
            return [_section_title("Vince Risk & Money Management", st),
                    Paragraph(f"<i>{v.get('error')}</i>", st["small"])]
        return []

    ps = v.get("position_sizing") or {}
    rows = [
        ("Optimal f",          _fmt(v.get("optimal_f"), "{:.4f}")),
        ("Kelly f",            _fmt(v.get("kelly_f"), "{:.4f}")),
        ("Biggest 1-Day Loss", _money(v.get("biggest_loss"))),
        ("Geometric Mean",     _fmt(v.get("geometric_mean"), "{:.4f}")),
        ("TWR",                _fmt(v.get("twr"), "{:.4f}")),
        ("AHPR",               _fmt(v.get("ahpr"), "{:.4f}")),
        ("Max Drawdown",       _pct(v.get("max_drawdown_pct"))),
        ("Current Drawdown",   _pct(v.get("current_drawdown_pct"))),
        ("Recommended Shares (50% f)", _fmt(v.get("recommended_shares"), "{:,}")),
        ("Risk per Trade",     _money(v.get("risk_per_trade"))),
        ("Sizing Status",      f"{v.get('sizing_status', '—')} (ratio {_fmt(v.get('sizing_ratio'))})"),
    ]
    label_w = content_w * 0.40
    val_w = content_w - label_w
    data = [[Paragraph(k, st["kv_label"]), Paragraph(str(val), st["body"])] for k, val in rows]
    tbl = Table(data, colWidths=[label_w, val_w])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, GREY_LIGHT),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GREY_LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [_section_title("Vince Risk & Money Management", st), tbl]


# ─────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────

def build_position_analysis_pdf(analysis: dict) -> bytes:
    """Render the position analysis dict to a PDF and return raw bytes."""
    if not analysis:
        analysis = {}

    pos = analysis.get("position") or {}
    ticker = pos.get("ticker", "Position")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=14 * mm,
        title=f"Position Analysis — {ticker}",
        author="Hiranya Trading Intelligence",
    )
    content_w = A4[0] - 24 * mm
    st = _styles()
    story: list = []

    story.extend(_build_header(analysis, st, content_w))

    # If the analyzer reported an error (insufficient data), surface
    # it cleanly instead of producing a blank PDF.
    if analysis.get("error"):
        story.append(Paragraph(
            f"<b>Could not analyze position:</b> {analysis['error']}",
            st["body"],
        ))
        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
        return buf.getvalue()

    sections = [
        _build_recommendation,
        _build_holding,
        _build_targets,
        _build_indicators,
        _build_method1,
        _build_buying_strategy_current,
        _build_all_strategies,
        _build_multi_system,
        _build_vince_risk,
    ]

    for builder in sections:
        try:
            elems = builder(analysis, st, content_w)
        except Exception as exc:  # never let one section take down the whole PDF
            elems = [Paragraph(
                f"<i>Section render error in {builder.__name__}: {exc}</i>",
                st["small"],
            )]
        if elems:
            story.extend(elems)
            story.append(Spacer(1, 6))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    page_num = canvas.getPageNumber()
    canvas.drawRightString(
        A4[0] - 12 * mm, 8 * mm,
        f"Page {page_num} • Hiranya Position Analysis"
    )
    canvas.drawString(
        12 * mm, 8 * mm,
        "Generated " + date.today().strftime("%d %b %Y") + " • For informational use only — not financial advice"
    )
    canvas.restoreState()
