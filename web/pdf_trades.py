"""
Server-side PDF builders for the Trades dashboard.

Two entry points:
  - build_trade_history_pdf(trades, user_name) — full trade ledger with
    summary metrics, per-trade charges/tax, monthly P&L breakdown.
  - build_fy_tax_summary_pdf(fy_summary, trades, user_name) — financial-year
    tax summary with detailed CG schedule, set-off and exemption notes.

Both produce A4 landscape PDFs via ReportLab so the wide tables fit comfortably
without horizontal scrolling.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
from typing import Any, Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
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
BRAND      = colors.HexColor("#1F4E78")
GREEN      = colors.HexColor("#0E8B3D")
RED        = colors.HexColor("#C0322B")
AMBER      = colors.HexColor("#B7791F")
PURPLE     = colors.HexColor("#6B2D9C")
GREY_DARK  = colors.HexColor("#1F2933")
GREY       = colors.HexColor("#6B7280")
GREY_LIGHT = colors.HexColor("#E5E7EB")
HEAD_BG    = colors.HexColor("#2E5A8A")
ROW_ALT    = colors.HexColor("#F3F6FA")
GREEN_BG   = colors.HexColor("#E8F5EC")
RED_BG     = colors.HexColor("#FBE8E6")


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
        "h3": ParagraphStyle(
            "H3", parent=base["Heading3"], fontSize=10,
            textColor=BRAND, spaceBefore=6, spaceAfter=3, leading=13,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=9,
            textColor=GREY_DARK, leading=12, spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"], fontSize=8,
            textColor=GREY, leading=11,
        ),
        "cell": ParagraphStyle(
            "Cell", parent=base["Normal"], fontSize=8,
            textColor=GREY_DARK, leading=10,
        ),
        "cell_right": ParagraphStyle(
            "CellRight", parent=base["Normal"], fontSize=8,
            textColor=GREY_DARK, leading=10, alignment=2,
        ),
        "kpi_label": ParagraphStyle(
            "KpiLabel", parent=base["Normal"], fontSize=8,
            textColor=GREY, leading=10, alignment=1,
        ),
        "kpi_value": ParagraphStyle(
            "KpiValue", parent=base["Normal"], fontSize=12,
            textColor=GREY_DARK, leading=14, alignment=1,
            fontName="Helvetica-Bold",
        ),
        "note": ParagraphStyle(
            "Note", parent=base["Normal"], fontSize=8,
            textColor=GREY_DARK, leading=11, leftIndent=8,
        ),
    }


# ─────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────

def _money(v: Any, blank_if_zero: bool = False) -> str:
    """Format as INR. Uses 'Rs.' prefix because ReportLab's default
    Helvetica is Latin-1 only and renders the Unicode rupee symbol
    as a tofu box."""
    if v is None or not isinstance(v, (int, float)):
        return "—"
    if blank_if_zero and abs(v) < 0.005:
        return "—"
    return f"Rs. {v:,.2f}"


def _money_plain(v: Any, blank_if_zero: bool = False) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "—"
    if blank_if_zero and abs(v) < 0.005:
        return "—"
    return f"{v:,.2f}"


def _pct(v: Any) -> str:
    if v is None or not isinstance(v, (int, float)):
        return "—"
    return f"{v:+.2f}%"


def _signed_money_html(v: float) -> str:
    """Return HTML-coloured INR string for use inside a Paragraph."""
    if v is None or not isinstance(v, (int, float)):
        return "—"
    color = GREEN.hexval() if v >= 0 else RED.hexval()
    sign = "" if v >= 0 else "-"
    return f"<font color='{color}'><b>{sign}Rs. {abs(v):,.2f}</b></font>"


def _section_title(text: str, st: dict) -> Paragraph:
    return Paragraph(text, st["h2"])


def _kpi_card(label: str, value: str, st: dict, value_color: colors.Color | None = None) -> Table:
    """Single KPI tile used in the summary band."""
    label_p = Paragraph(label.upper(), st["kpi_label"])
    if value_color is None:
        value_p = Paragraph(value, st["kpi_value"])
    else:
        value_p = Paragraph(
            f"<font color='{value_color.hexval()}'>{value}</font>",
            st["kpi_value"],
        )
    tbl = Table([[label_p], [value_p]], colWidths=[None])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, GREY_LIGHT),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
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


def _grid_table(headers: list[str], rows: list[list[Any]],
                col_widths: list[float],
                color_cells: list[tuple] | None = None,
                font_size: float = 8.0) -> Table:
    """A compact data table with a coloured header band."""
    data = [headers] + rows
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), font_size),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("FONTSIZE", (0, 1), (-1, -1), font_size),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BFCBD7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, ROW_ALT]),
    ]
    if color_cells:
        style.extend(color_cells)
    tbl.setStyle(TableStyle(style))
    return tbl


def _platform_label(p: str) -> str:
    p = (p or "").lower()
    if p == "zerodha":
        return "Zerodha"
    if p == "dhan":
        return "Dhan"
    return p.title() or "—"


def _type_label(t: str) -> str:
    t = (t or "").lower()
    if t == "delivery":
        return "Delivery"
    if t == "intraday":
        return "Intraday"
    return t.title() or "—"


def _fy_label_for(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "—"
    if d.month >= 4:
        return f"FY {d.year}-{str(d.year+1)[-2:]}"
    return f"FY {d.year-1}-{str(d.year)[-2:]}"


# ─────────────────────────────────────────────────────────────────
#  Summary aggregations
# ─────────────────────────────────────────────────────────────────

def _aggregate_overview(trades: list[dict]) -> dict:
    """Compute summary numbers across all trades."""
    n = len(trades)
    invested = gross = charges = tax = net_pnl = post_tax = 0.0
    win_count = loss_count = 0
    win_sum = loss_sum = 0.0
    by_cat: dict[str, dict] = defaultdict(lambda: {"count": 0, "net": 0.0, "tax": 0.0})
    by_platform: dict[str, dict] = defaultdict(lambda: {"count": 0, "net": 0.0, "charges": 0.0})

    for t in trades:
        p = t.get("pnl") or {}
        invested += p.get("buy_value", 0) or 0
        gross    += p.get("gross_pnl", 0) or 0
        c = p.get("charges", {}) or {}
        charges  += c.get("total", 0) or 0
        tax      += p.get("total_tax", 0) or 0
        net      = p.get("net_pnl", 0) or 0
        net_pnl  += net
        post_tax += p.get("post_tax_pnl", 0) or 0
        if net >= 0:
            win_count += 1
            win_sum += net
        else:
            loss_count += 1
            loss_sum += net

        cat = p.get("tax_category") or "—"
        by_cat[cat]["count"] += 1
        by_cat[cat]["net"]   += net
        by_cat[cat]["tax"]   += p.get("total_tax", 0) or 0

        plat = _platform_label(t.get("platform"))
        by_platform[plat]["count"]   += 1
        by_platform[plat]["net"]     += net
        by_platform[plat]["charges"] += c.get("total", 0) or 0

    win_rate = (win_count / n * 100) if n else 0.0
    avg_win = (win_sum / win_count) if win_count else 0.0
    avg_loss = (loss_sum / loss_count) if loss_count else 0.0
    pf = (win_sum / abs(loss_sum)) if loss_sum < 0 else None

    return {
        "n":          n,
        "invested":   invested,
        "gross":      gross,
        "charges":    charges,
        "tax":        tax,
        "net_pnl":    net_pnl,
        "post_tax":   post_tax,
        "win_count":  win_count,
        "loss_count": loss_count,
        "win_rate":   win_rate,
        "avg_win":    avg_win,
        "avg_loss":   avg_loss,
        "profit_factor": pf,
        "by_cat":      dict(by_cat),
        "by_platform": dict(by_platform),
    }


def _aggregate_monthly(trades: list[dict]) -> list[dict]:
    """Bucket trades by sell-month."""
    buckets: dict[str, dict] = defaultdict(lambda: {
        "trades": 0, "gross": 0.0, "charges": 0.0,
        "net": 0.0, "tax": 0.0, "post_tax": 0.0,
    })
    for t in trades:
        p = t.get("pnl") or {}
        m = (t.get("sell_date") or "")[:7]
        if not m:
            continue
        b = buckets[m]
        b["trades"]   += 1
        b["gross"]    += p.get("gross_pnl", 0) or 0
        b["charges"]  += (p.get("charges") or {}).get("total", 0) or 0
        b["net"]      += p.get("net_pnl", 0) or 0
        b["tax"]      += p.get("total_tax", 0) or 0
        b["post_tax"] += p.get("post_tax_pnl", 0) or 0
    return [{"month": m, **buckets[m]} for m in sorted(buckets)]


def _aggregate_per_stock(trades: list[dict]) -> list[dict]:
    """Bucket trades by stock symbol — best/worst performers."""
    buckets: dict[str, dict] = defaultdict(lambda: {
        "trades": 0, "qty": 0, "invested": 0.0,
        "net": 0.0, "tax": 0.0, "post_tax": 0.0,
    })
    for t in trades:
        p = t.get("pnl") or {}
        s = (t.get("stock") or "—").upper()
        b = buckets[s]
        b["trades"]   += 1
        b["qty"]      += int(t.get("quantity", 0) or 0)
        b["invested"] += p.get("buy_value", 0) or 0
        b["net"]      += p.get("net_pnl", 0) or 0
        b["tax"]      += p.get("total_tax", 0) or 0
        b["post_tax"] += p.get("post_tax_pnl", 0) or 0
    rows = [{"stock": s, **v} for s, v in buckets.items()]
    rows.sort(key=lambda r: r["net"], reverse=True)
    return rows


# ─────────────────────────────────────────────────────────────────
#  Section builders — Trade History PDF
# ─────────────────────────────────────────────────────────────────

def _build_header(st: dict, title: str, subtitle: str) -> list:
    return [
        Paragraph(title, st["title"]),
        Paragraph(subtitle, st["subtitle"]),
    ]


def _build_summary_band(agg: dict, st: dict, content_w: float) -> list:
    """Top KPI row — counts, P&L, charges, tax, net."""
    net_color = GREEN if agg["net_pnl"] >= 0 else RED
    post_color = GREEN if agg["post_tax"] >= 0 else RED
    gross_color = GREEN if agg["gross"] >= 0 else RED

    cards = [
        _kpi_card("Total Trades",  f"{agg['n']:,}", st),
        _kpi_card("Invested",      _money(agg["invested"]), st),
        _kpi_card("Gross P&amp;L", _money(agg["gross"]), st, gross_color),
        _kpi_card("Total Charges", _money(agg["charges"]), st, AMBER),
        _kpi_card("Est. Tax",      _money(agg["tax"]), st, PURPLE),
        _kpi_card("Net P&amp;L",   _money(agg["net_pnl"]), st, net_color),
        _kpi_card("Post-Tax",      _money(agg["post_tax"]), st, post_color),
    ]
    return [
        _section_title("Performance Snapshot", st),
        _kpi_row(cards, content_w),
        Spacer(1, 4),
    ]


def _build_quality_band(agg: dict, st: dict, content_w: float) -> list:
    """Win-rate / payoff metrics."""
    pf = agg["profit_factor"]
    pf_str = f"{pf:.2f}" if pf is not None else "—"
    cards = [
        _kpi_card("Wins / Losses",
                  f"{agg['win_count']} / {agg['loss_count']}", st),
        _kpi_card("Win Rate",
                  f"{agg['win_rate']:.1f}%", st,
                  GREEN if agg["win_rate"] >= 50 else AMBER),
        _kpi_card("Avg Win",
                  _money(agg["avg_win"]), st, GREEN),
        _kpi_card("Avg Loss",
                  _money(agg["avg_loss"]), st, RED),
        _kpi_card("Profit Factor",
                  pf_str, st,
                  GREEN if (pf is not None and pf >= 1.5) else AMBER),
    ]
    return [
        _kpi_row(cards, content_w),
        Spacer(1, 6),
    ]


def _build_trade_ledger(trades: list[dict], st: dict, content_w: float) -> list:
    """Full per-trade table — the heart of the Trade History export."""
    if not trades:
        return [
            _section_title("Trade History", st),
            Paragraph("<i>No trades recorded yet.</i>", st["body"]),
        ]

    headers = [
        "#", "Stock", "Plat.", "Type", "Buy Date", "Sell Date",
        "Qty", "Buy", "Sell", "Gross", "Charges", "Net", "Tax", "Post-Tax",
        "Ret %", "Cat",
    ]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []

    # Sort by sell_date desc — most recent first, matching the dashboard.
    sorted_trades = sorted(
        trades, key=lambda t: (t.get("sell_date") or "", t.get("id") or 0), reverse=True,
    )

    for i, t in enumerate(sorted_trades, start=1):
        p = t.get("pnl") or {}
        c = p.get("charges") or {}
        gross = p.get("gross_pnl", 0) or 0
        net = p.get("net_pnl", 0) or 0
        post = p.get("post_tax_pnl", 0) or 0
        ret = p.get("return_pct", 0) or 0

        rows.append([
            str(i),
            (t.get("stock") or "—").upper(),
            _platform_label(t.get("platform")),
            _type_label(t.get("trade_type")),
            t.get("buy_date") or "—",
            t.get("sell_date") or "—",
            f"{int(t.get('quantity', 0) or 0):,}",
            _money_plain(t.get("buy_price")),
            _money_plain(t.get("sell_price")),
            _money_plain(gross),
            _money_plain(c.get("total")),
            _money_plain(net),
            _money_plain(p.get("total_tax"), blank_if_zero=True),
            _money_plain(post),
            f"{ret:+.2f}%",
            p.get("tax_category") or "—",
        ])

        # Colour P&L columns
        gross_c = GREEN if gross >= 0 else RED
        net_c   = GREEN if net   >= 0 else RED
        post_c  = GREEN if post  >= 0 else RED
        ret_c   = GREEN if ret   >= 0 else RED
        color_cells += [
            ("TEXTCOLOR", (9,  i), (9,  i), gross_c),
            ("TEXTCOLOR", (10, i), (10, i), AMBER),
            ("TEXTCOLOR", (11, i), (11, i), net_c),
            ("FONTNAME",  (11, i), (11, i), "Helvetica-Bold"),
            ("TEXTCOLOR", (12, i), (12, i), PURPLE),
            ("TEXTCOLOR", (13, i), (13, i), post_c),
            ("TEXTCOLOR", (14, i), (14, i), ret_c),
            ("ALIGN",     (6,  i), (14, i), "RIGHT"),
        ]
        # Tax category badge tint
        cat = (p.get("tax_category") or "").upper()
        if cat == "STCG":
            color_cells.append(("TEXTCOLOR", (15, i), (15, i), RED))
        elif cat == "LTCG":
            color_cells.append(("TEXTCOLOR", (15, i), (15, i), GREEN))
        elif cat == "SPECULATIVE":
            color_cells.append(("TEXTCOLOR", (15, i), (15, i), PURPLE))

    # Column widths sized for landscape A4 (~273mm content)
    cw = [
        content_w * 0.030,  # #
        content_w * 0.085,  # Stock
        content_w * 0.055,  # Platform
        content_w * 0.060,  # Type
        content_w * 0.065,  # Buy Date
        content_w * 0.065,  # Sell Date
        content_w * 0.045,  # Qty
        content_w * 0.060,  # Buy
        content_w * 0.060,  # Sell
        content_w * 0.075,  # Gross
        content_w * 0.075,  # Charges
        content_w * 0.080,  # Net
        content_w * 0.065,  # Tax
        content_w * 0.080,  # Post-Tax
        content_w * 0.055,  # Ret %
        content_w * 0.045,  # Cat
    ]

    color_cells.append(("ALIGN", (0, 0), (0, -1), "CENTER"))
    color_cells.append(("ALIGN", (15, 0), (15, -1), "CENTER"))

    tbl = _grid_table(headers, rows, cw, color_cells, font_size=7.5)
    return [_section_title("Trade History — Detailed Ledger", st), tbl]


def _build_charges_breakdown(trades: list[dict], st: dict, content_w: float) -> list:
    """Aggregate of every charge component across all trades."""
    if not trades:
        return []

    keys = [
        ("brokerage_buy",  "Brokerage (Buy)"),
        ("brokerage_sell", "Brokerage (Sell)"),
        ("stt_buy",        "STT (Buy)"),
        ("stt_sell",       "STT (Sell)"),
        ("exchange_buy",   "Exchange Txn (Buy)"),
        ("exchange_sell",  "Exchange Txn (Sell)"),
        ("sebi",           "SEBI Charges"),
        ("stamp_duty",     "Stamp Duty (Buy)"),
        ("dp_charges",     "DP Charges"),
        ("gst",            "GST (18%)"),
    ]
    totals: dict[str, float] = {k: 0.0 for k, _ in keys}
    for t in trades:
        c = (t.get("pnl") or {}).get("charges") or {}
        for k, _ in keys:
            totals[k] += c.get(k, 0) or 0

    grand = sum(totals.values())
    rows = []
    for k, label in keys:
        share = (totals[k] / grand * 100) if grand else 0
        rows.append([label, _money(totals[k]), f"{share:.1f}%"])
    rows.append([
        Paragraph("<b>TOTAL</b>", st["cell"]),
        Paragraph(f"<b>{_money(grand)}</b>", st["cell"]),
        Paragraph("<b>100.0%</b>", st["cell"]),
    ])

    cw = [content_w * 0.55, content_w * 0.30, content_w * 0.15]
    tbl = _grid_table(["Component", "Amount", "Share"], rows, cw)
    return [
        _section_title("Aggregate Charges Breakdown", st),
        Paragraph(
            "Sum of every regulatory and brokerage charge across all trades — "
            "useful for cross-checking against broker contract notes.",
            st["small"],
        ),
        Spacer(1, 3),
        tbl,
    ]


def _build_monthly(trades: list[dict], st: dict, content_w: float) -> list:
    rows_data = _aggregate_monthly(trades)
    if not rows_data:
        return []

    headers = ["Month", "Trades", "Gross P&L", "Charges", "Net P&L", "Tax", "Post-Tax"]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    for i, r in enumerate(rows_data, start=1):
        net = r["net"]
        post = r["post_tax"]
        rows.append([
            r["month"],
            f"{r['trades']:,}",
            _money_plain(r["gross"]),
            _money_plain(r["charges"]),
            _money_plain(net),
            _money_plain(r["tax"], blank_if_zero=True),
            _money_plain(post),
        ])
        net_c = GREEN if net >= 0 else RED
        post_c = GREEN if post >= 0 else RED
        color_cells += [
            ("TEXTCOLOR", (4, i), (4, i), net_c),
            ("FONTNAME",  (4, i), (4, i), "Helvetica-Bold"),
            ("TEXTCOLOR", (6, i), (6, i), post_c),
            ("ALIGN",     (1, i), (6, i), "RIGHT"),
        ]

    cw = [
        content_w * 0.12, content_w * 0.10,
        content_w * 0.16, content_w * 0.16,
        content_w * 0.16, content_w * 0.14, content_w * 0.16,
    ]
    tbl = _grid_table(headers, rows, cw, color_cells)
    return [_section_title("Monthly P&L Breakdown", st), tbl]


def _build_per_stock(trades: list[dict], st: dict, content_w: float, top_n: int = 15) -> list:
    rows_data = _aggregate_per_stock(trades)
    if not rows_data:
        return []

    headers = ["Stock", "Trades", "Qty", "Invested", "Net P&L", "Tax", "Post-Tax"]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    shown = rows_data[:top_n] + (rows_data[-top_n:] if len(rows_data) > 2 * top_n else [])
    seen = set()
    deduped = []
    for r in shown:
        if r["stock"] not in seen:
            deduped.append(r)
            seen.add(r["stock"])

    for i, r in enumerate(deduped, start=1):
        net = r["net"]
        post = r["post_tax"]
        rows.append([
            r["stock"],
            f"{r['trades']:,}",
            f"{r['qty']:,}",
            _money_plain(r["invested"]),
            _money_plain(net),
            _money_plain(r["tax"], blank_if_zero=True),
            _money_plain(post),
        ])
        net_c = GREEN if net >= 0 else RED
        post_c = GREEN if post >= 0 else RED
        color_cells += [
            ("TEXTCOLOR", (4, i), (4, i), net_c),
            ("FONTNAME",  (4, i), (4, i), "Helvetica-Bold"),
            ("TEXTCOLOR", (6, i), (6, i), post_c),
            ("ALIGN",     (1, i), (6, i), "RIGHT"),
        ]

    cw = [
        content_w * 0.16, content_w * 0.10, content_w * 0.10,
        content_w * 0.18, content_w * 0.16, content_w * 0.14, content_w * 0.16,
    ]
    tbl = _grid_table(headers, rows, cw, color_cells)
    note = Paragraph(
        f"Top &amp; bottom performers by net P&amp;L (showing {len(deduped)} of "
        f"{len(rows_data)} unique symbols).",
        st["small"],
    )
    return [_section_title("Per-Stock Performance", st), note, Spacer(1, 3), tbl]


def _build_category_split(agg: dict, st: dict, content_w: float) -> list:
    by_cat = agg["by_cat"]
    if not by_cat:
        return []
    headers = ["Tax Category", "Trades", "Net P&L", "Est. Tax"]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    for i, (cat, v) in enumerate(sorted(by_cat.items()), start=1):
        net = v["net"]
        net_c = GREEN if net >= 0 else RED
        rows.append([cat, f"{v['count']:,}", _money_plain(net), _money_plain(v["tax"], blank_if_zero=True)])
        color_cells += [
            ("TEXTCOLOR", (2, i), (2, i), net_c),
            ("FONTNAME",  (2, i), (2, i), "Helvetica-Bold"),
            ("ALIGN",     (1, i), (3, i), "RIGHT"),
        ]
    cw = [content_w * 0.40, content_w * 0.20, content_w * 0.20, content_w * 0.20]
    return [
        _section_title("Tax Category Split", st),
        _grid_table(headers, rows, cw, color_cells),
    ]


def _build_platform_split(agg: dict, st: dict, content_w: float) -> list:
    by_p = agg["by_platform"]
    if not by_p:
        return []
    headers = ["Platform", "Trades", "Net P&L", "Charges"]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    for i, (plat, v) in enumerate(sorted(by_p.items()), start=1):
        net = v["net"]
        net_c = GREEN if net >= 0 else RED
        rows.append([plat, f"{v['count']:,}", _money_plain(net), _money_plain(v["charges"])])
        color_cells += [
            ("TEXTCOLOR", (2, i), (2, i), net_c),
            ("FONTNAME",  (2, i), (2, i), "Helvetica-Bold"),
            ("TEXTCOLOR", (3, i), (3, i), AMBER),
            ("ALIGN",     (1, i), (3, i), "RIGHT"),
        ]
    cw = [content_w * 0.40, content_w * 0.20, content_w * 0.20, content_w * 0.20]
    return [
        _section_title("Platform Split", st),
        _grid_table(headers, rows, cw, color_cells),
    ]


def _build_disclaimer(st: dict) -> list:
    return [
        Spacer(1, 6),
        Paragraph(
            "<b>Disclaimer:</b> This report is generated from trades you entered "
            "into Hiranya. Charges follow the published rate cards for Zerodha and "
            "Dhan; tax computations apply Indian income-tax rules in effect for "
            "FY 2024-25 onwards (STCG 20%, LTCG 12.5% with Rs. 1,25,000 exemption "
            "per FY, intraday taxed at slab — 30% indicative). Use this as a "
            "working document; always reconcile with broker contract notes and "
            "your AIS / 26AS before filing.",
            st["small"],
        ),
    ]


# ─────────────────────────────────────────────────────────────────
#  Section builders — FY Tax Summary PDF
# ─────────────────────────────────────────────────────────────────

def _build_fy_overview_band(fy_summary: list[dict], st: dict, content_w: float) -> list:
    """Top KPI row over all FYs."""
    if not fy_summary:
        return []
    n = len(fy_summary)
    total_trades = sum(f.get("trade_count", 0) for f in fy_summary)
    total_charges = sum(f.get("total_charges", 0) for f in fy_summary)
    total_tax = sum(f.get("total_tax", 0) for f in fy_summary)
    total_stcg = sum(f.get("stcg_tax", 0) for f in fy_summary)
    total_ltcg = sum(f.get("ltcg_tax", 0) for f in fy_summary)
    total_spec = sum(f.get("speculative_tax", 0) for f in fy_summary)

    cards = [
        _kpi_card("FYs Covered",  f"{n}", st),
        _kpi_card("Total Trades", f"{total_trades:,}", st),
        _kpi_card("STCG Tax",     _money(total_stcg), st, RED),
        _kpi_card("LTCG Tax",     _money(total_ltcg), st, GREEN),
        _kpi_card("Spec. Tax",    _money(total_spec), st, PURPLE),
        _kpi_card("Total Charges", _money(total_charges), st, AMBER),
        _kpi_card("Total Tax",    _money(total_tax), st, PURPLE),
    ]
    return [
        _section_title("Tax Liability Snapshot — All Financial Years", st),
        _kpi_row(cards, content_w),
        Spacer(1, 6),
    ]


def _build_fy_master_table(fy_summary: list[dict], st: dict, content_w: float) -> list:
    """The detailed FY × tax-head matrix."""
    if not fy_summary:
        return [Paragraph("<i>No FY data available.</i>", st["body"])]

    headers = [
        "Financial Year", "Trades",
        "STCG Profit", "STCG Loss", "STCG Tax",
        "LTCG Profit", "LTCG Loss", "LTCG Exempt", "LTCG Tax",
        "Spec. Tax", "Cess", "Charges", "Total Tax",
    ]
    rows: list[list[Any]] = []
    color_cells: list[tuple] = []
    for i, f in enumerate(fy_summary, start=1):
        rows.append([
            f.get("fy", "—"),
            f"{f.get('trade_count', 0):,}",
            _money_plain(f.get("stcg_profit"), blank_if_zero=True),
            _money_plain(f.get("stcg_loss"),   blank_if_zero=True),
            _money_plain(f.get("stcg_tax"),    blank_if_zero=True),
            _money_plain(f.get("ltcg_profit"), blank_if_zero=True),
            _money_plain(f.get("ltcg_loss"),   blank_if_zero=True),
            _money_plain(f.get("ltcg_exemption"), blank_if_zero=True),
            _money_plain(f.get("ltcg_tax"),    blank_if_zero=True),
            _money_plain(f.get("speculative_tax"), blank_if_zero=True),
            _money_plain(f.get("cess"),        blank_if_zero=True),
            _money_plain(f.get("total_charges")),
            _money_plain(f.get("total_tax")),
        ])
        color_cells += [
            ("TEXTCOLOR", (2, i), (2, i), GREEN),
            ("TEXTCOLOR", (3, i), (3, i), RED),
            ("TEXTCOLOR", (4, i), (4, i), RED),
            ("TEXTCOLOR", (5, i), (5, i), GREEN),
            ("TEXTCOLOR", (6, i), (6, i), RED),
            ("TEXTCOLOR", (7, i), (7, i), colors.HexColor("#0E7490")),
            ("TEXTCOLOR", (11, i), (11, i), AMBER),
            ("TEXTCOLOR", (12, i), (12, i), PURPLE),
            ("FONTNAME",  (12, i), (12, i), "Helvetica-Bold"),
            ("ALIGN",     (1, i), (12, i), "RIGHT"),
        ]

    # Footer totals row
    total_idx = len(rows) + 1
    sums = {k: sum((f.get(k) or 0) for f in fy_summary) for k in [
        "trade_count", "stcg_profit", "stcg_loss", "stcg_tax",
        "ltcg_profit", "ltcg_loss", "ltcg_exemption", "ltcg_tax",
        "speculative_tax", "cess", "total_charges", "total_tax",
    ]}
    rows.append([
        Paragraph("<b>TOTAL</b>", st["cell"]),
        Paragraph(f"<b>{sums['trade_count']:,}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['stcg_profit'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['stcg_loss'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['stcg_tax'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['ltcg_profit'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['ltcg_loss'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['ltcg_exemption'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['ltcg_tax'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['speculative_tax'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['cess'], blank_if_zero=True)}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['total_charges'])}</b>", st["cell_right"]),
        Paragraph(f"<b>{_money_plain(sums['total_tax'])}</b>", st["cell_right"]),
    ])
    color_cells.append(("BACKGROUND", (0, total_idx), (-1, total_idx), colors.HexColor("#EEF2F7")))
    color_cells.append(("LINEABOVE",  (0, total_idx), (-1, total_idx), 1.0, BRAND))

    cw = [
        content_w * 0.10, content_w * 0.05,
        content_w * 0.08, content_w * 0.08, content_w * 0.07,
        content_w * 0.08, content_w * 0.08, content_w * 0.08, content_w * 0.07,
        content_w * 0.07, content_w * 0.05, content_w * 0.08, content_w * 0.11,
    ]
    tbl = _grid_table(headers, rows, cw, color_cells, font_size=7.5)
    return [_section_title("Financial-Year Tax Schedule", st), tbl]


def _build_fy_per_year_detail(fy_summary: list[dict], trades: list[dict], st: dict, content_w: float) -> list:
    """One sub-block per FY: ITR-style breakdown plus contributing trades."""
    if not fy_summary or not trades:
        return []

    # Bucket trades by FY using their sell_date
    by_fy: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        fy = _fy_label_for(t.get("sell_date") or "")
        by_fy[fy].append(t)

    elems: list = [_section_title("Per-Year ITR-Style Breakdown", st)]
    for f in fy_summary:
        fy = f.get("fy", "—")
        elems.append(Spacer(1, 4))
        elems.append(Paragraph(
            f"<b>{fy}</b> — {f.get('trade_count', 0):,} trade(s)",
            st["h3"],
        ))

        # Loss set-off / exemption commentary
        commentary = []
        if (f.get("stcg_loss", 0) or 0) > (f.get("stcg_profit", 0) or 0):
            commentary.append(
                f"Net STCG loss of {_money(f.get('stcg_loss', 0) - f.get('stcg_profit', 0))} "
                "is set off first against LTCG; any residual is carried forward (ITR-2 schedule CFL)."
            )
        if (f.get("ltcg_exemption", 0) or 0) > 0:
            commentary.append(
                f"LTCG exemption of {_money(f.get('ltcg_exemption'))} applied "
                "(Sec 112A — first Rs. 1,25,000 of net LTCG per FY is tax-free)."
            )
        if (f.get("speculative_tax", 0) or 0) > 0:
            commentary.append(
                "Intraday equity is treated as Speculative Business Income — "
                "actual tax is at your slab (30% shown is indicative top-bracket)."
            )

        if commentary:
            for line in commentary:
                elems.append(Paragraph(f"• {line}", st["note"]))
            elems.append(Spacer(1, 2))

        # ITR head-wise table
        itr_rows = [
            ["Schedule CG — Short Term (Sec 111A, 20%)",
             _money(f.get("stcg_profit", 0)),
             _money(-(f.get("stcg_loss", 0) or 0), blank_if_zero=True),
             _money(max(0, (f.get("stcg_profit", 0) or 0) - (f.get("stcg_loss", 0) or 0))),
             _money(f.get("stcg_tax", 0), blank_if_zero=True)],
            ["Schedule CG — Long Term (Sec 112A, 12.5%)",
             _money(f.get("ltcg_profit", 0)),
             _money(-(f.get("ltcg_loss", 0) or 0), blank_if_zero=True),
             _money(max(0, (f.get("ltcg_profit", 0) or 0) - (f.get("ltcg_loss", 0) or 0) - (f.get("ltcg_exemption", 0) or 0))),
             _money(f.get("ltcg_tax", 0), blank_if_zero=True)],
            ["Schedule BP — Speculative (Intraday, slab)",
             _money(f.get("speculative_profit", 0) if f.get("speculative_profit") is not None else 0),
             _money(-(f.get("speculative_loss", 0) or 0) if f.get("speculative_loss") is not None else 0, blank_if_zero=True),
             "—",
             _money(f.get("speculative_tax", 0), blank_if_zero=True)],
        ]
        cw_itr = [content_w * 0.40, content_w * 0.15, content_w * 0.15,
                  content_w * 0.15, content_w * 0.15]
        itr_tbl = _grid_table(
            ["Head", "Profit", "Loss", "Taxable", "Tax"],
            itr_rows, cw_itr,
        )
        elems.append(itr_tbl)
        elems.append(Spacer(1, 3))

        # Footer line: cess + total
        bottom = Paragraph(
            f"<b>Sub-total tax:</b> {_money((f.get('stcg_tax', 0) or 0) + (f.get('ltcg_tax', 0) or 0) + (f.get('speculative_tax', 0) or 0))} "
            f"&nbsp;&nbsp; <b>Health &amp; Edu Cess (4%):</b> {_money(f.get('cess', 0))} "
            f"&nbsp;&nbsp; <b>Total Tax Payable:</b> "
            f"<font color='{PURPLE.hexval()}'><b>{_money(f.get('total_tax', 0))}</b></font> "
            f"&nbsp;&nbsp; <b>Total Charges:</b> "
            f"<font color='{AMBER.hexval()}'>{_money(f.get('total_charges', 0))}</font>",
            st["body"],
        )
        elems.append(bottom)

        # Contributing trades table for this FY (compact)
        fy_trades = sorted(by_fy.get(fy, []), key=lambda t: t.get("sell_date") or "")
        if fy_trades:
            elems.append(Spacer(1, 4))
            elems.append(Paragraph("Contributing Trades", st["h3"]))
            sub_headers = ["Sell Date", "Stock", "Type", "Qty", "Buy", "Sell",
                           "Net P&L", "Cat", "Tax"]
            sub_rows: list[list[Any]] = []
            sub_color: list[tuple] = []
            for j, t in enumerate(fy_trades, start=1):
                p = t.get("pnl") or {}
                net = p.get("net_pnl", 0) or 0
                sub_rows.append([
                    t.get("sell_date") or "—",
                    (t.get("stock") or "—").upper(),
                    _type_label(t.get("trade_type")),
                    f"{int(t.get('quantity', 0) or 0):,}",
                    _money_plain(t.get("buy_price")),
                    _money_plain(t.get("sell_price")),
                    _money_plain(net),
                    p.get("tax_category") or "—",
                    _money_plain(p.get("total_tax"), blank_if_zero=True),
                ])
                sub_color += [
                    ("TEXTCOLOR", (6, j), (6, j), GREEN if net >= 0 else RED),
                    ("FONTNAME",  (6, j), (6, j), "Helvetica-Bold"),
                    ("ALIGN",     (3, j), (8, j), "RIGHT"),
                ]
            cw_sub = [
                content_w * 0.10, content_w * 0.13, content_w * 0.10,
                content_w * 0.08, content_w * 0.10, content_w * 0.10,
                content_w * 0.13, content_w * 0.10, content_w * 0.16,
            ]
            elems.append(_grid_table(sub_headers, sub_rows, cw_sub, sub_color, font_size=7.5))

        elems.append(Spacer(1, 8))

    return elems


def _build_fy_legend(st: dict) -> list:
    return [
        Spacer(1, 6),
        _section_title("Tax Rules Applied", st),
        Paragraph(
            "<b>STCG (Sec 111A):</b> Equity sold within 12 months. Flat 20% "
            "on net gains (after intra-head loss set-off).",
            st["body"],
        ),
        Paragraph(
            "<b>LTCG (Sec 112A):</b> Equity held &gt; 12 months. First "
            "Rs. 1,25,000 of aggregate net LTCG per FY is exempt; balance "
            "taxed at 12.5% without indexation.",
            st["body"],
        ),
        Paragraph(
            "<b>Speculative Business Income:</b> Equity intraday is "
            "speculative under Sec 43(5). Reported under PGBP and taxed "
            "at slab — 30% used here as a conservative top-bracket estimate.",
            st["body"],
        ),
        Paragraph(
            "<b>Loss set-off:</b> Short-term loss is first netted against "
            "STCG; any excess offsets LTCG. Speculative loss can only be "
            "set off against speculative profit (carried forward 4 years).",
            st["body"],
        ),
        Paragraph(
            "<b>Cess:</b> Health &amp; Education Cess of 4% is added on the "
            "computed tax (not on charges).",
            st["body"],
        ),
        Spacer(1, 4),
        Paragraph(
            "<b>Disclaimer:</b> Indicative only. Verify against your AIS / "
            "26AS / broker contract notes and consult a tax professional "
            "before filing.",
            st["small"],
        ),
    ]


# ─────────────────────────────────────────────────────────────────
#  Footer
# ─────────────────────────────────────────────────────────────────

def _make_footer(report_label: str):
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GREY)
        page_num = canvas.getPageNumber()
        page_w, _ = doc.pagesize
        canvas.drawRightString(
            page_w - 12 * mm, 8 * mm,
            f"Page {page_num} • Hiranya {report_label}",
        )
        canvas.drawString(
            12 * mm, 8 * mm,
            f"Generated {date.today().strftime('%d %b %Y')} • For informational use only — not financial advice",
        )
        canvas.restoreState()
    return _footer


# ─────────────────────────────────────────────────────────────────
#  Public entry points
# ─────────────────────────────────────────────────────────────────

def build_trade_history_pdf(trades: list[dict], user_name: str | None = None) -> bytes:
    """Produce a comprehensive PDF report of every trade entered."""
    trades = trades or []
    agg = _aggregate_overview(trades)

    buf = BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=14 * mm,
        title="Hiranya — Trade History",
        author="Hiranya Trading Intelligence",
    )
    content_w = page[0] - 20 * mm
    st = _styles()
    story: list = []

    subtitle_bits = [f"Generated {date.today().strftime('%d %b %Y')}"]
    if user_name:
        subtitle_bits.append(f"Account: <b>{user_name}</b>")
    subtitle_bits.append(f"{agg['n']:,} trade(s) on file")
    story.extend(_build_header(
        st,
        "Trade History &amp; P&amp;L Report",
        " &nbsp;&bull;&nbsp; ".join(subtitle_bits),
    ))

    if not trades:
        story.append(Paragraph(
            "<i>No trades have been recorded yet — add a trade on the "
            "Trades dashboard to populate this report.</i>",
            st["body"],
        ))
        doc.build(story, onFirstPage=_make_footer("Trade History"),
                  onLaterPages=_make_footer("Trade History"))
        return buf.getvalue()

    sections = [
        lambda: _build_summary_band(agg, st, content_w),
        lambda: _build_quality_band(agg, st, content_w),
        lambda: _build_trade_ledger(trades, st, content_w),
        lambda: [PageBreak()],
        lambda: _build_charges_breakdown(trades, st, content_w),
        lambda: [Spacer(1, 6)],
        lambda: _build_monthly(trades, st, content_w),
        lambda: [Spacer(1, 6)],
        lambda: _build_category_split(agg, st, content_w),
        lambda: [Spacer(1, 6)],
        lambda: _build_platform_split(agg, st, content_w),
        lambda: [Spacer(1, 6)],
        lambda: _build_per_stock(trades, st, content_w),
        lambda: _build_disclaimer(st),
    ]

    for build in sections:
        try:
            elems = build()
        except Exception as exc:  # never let one section take down the whole PDF
            elems = [Paragraph(
                f"<i>Section render error: {exc}</i>", st["small"],
            )]
        if elems:
            story.extend(elems)

    doc.build(
        story,
        onFirstPage=_make_footer("Trade History"),
        onLaterPages=_make_footer("Trade History"),
    )
    return buf.getvalue()


def build_fy_tax_summary_pdf(fy_summary: list[dict],
                             trades: list[dict] | None = None,
                             user_name: str | None = None) -> bytes:
    """Produce an ITR-ready Financial Year tax summary PDF."""
    fy_summary = fy_summary or []
    trades = trades or []

    buf = BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=14 * mm,
        title="Hiranya — Financial Year Tax Summary",
        author="Hiranya Trading Intelligence",
    )
    content_w = page[0] - 20 * mm
    st = _styles()
    story: list = []

    subtitle_bits = [f"Generated {date.today().strftime('%d %b %Y')}"]
    if user_name:
        subtitle_bits.append(f"Account: <b>{user_name}</b>")
    if fy_summary:
        first_fy = fy_summary[0].get("fy", "—")
        last_fy = fy_summary[-1].get("fy", "—")
        span = first_fy if first_fy == last_fy else f"{first_fy} → {last_fy}"
        subtitle_bits.append(f"Years covered: <b>{span}</b>")

    story.extend(_build_header(
        st,
        "Financial Year Tax Summary",
        " &nbsp;&bull;&nbsp; ".join(subtitle_bits),
    ))

    if not fy_summary:
        story.append(Paragraph(
            "<i>No tax-relevant trades have been recorded yet.</i>",
            st["body"],
        ))
        doc.build(story, onFirstPage=_make_footer("FY Tax Summary"),
                  onLaterPages=_make_footer("FY Tax Summary"))
        return buf.getvalue()

    sections = [
        lambda: _build_fy_overview_band(fy_summary, st, content_w),
        lambda: _build_fy_master_table(fy_summary, st, content_w),
        lambda: [PageBreak()],
        lambda: _build_fy_per_year_detail(fy_summary, trades, st, content_w),
        lambda: _build_fy_legend(st),
    ]

    for build in sections:
        try:
            elems = build()
        except Exception as exc:
            elems = [Paragraph(
                f"<i>Section render error: {exc}</i>", st["small"],
            )]
        if elems:
            story.extend(elems)

    doc.build(
        story,
        onFirstPage=_make_footer("FY Tax Summary"),
        onLaterPages=_make_footer("FY Tax Summary"),
    )
    return buf.getvalue()
