"""
display.py — Rich terminal display engine.
Creates a beautiful, information-dense output using the rich library.
Layout: dashboard-style panels with fundamental analysis.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.rule import Rule
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich import box
from rich.align import Align
from rich.layout import Layout
import math
from typing import Optional

from bb_squeeze.signals import SignalResult
from bb_squeeze.fundamentals import FundamentalData
from bb_squeeze.config import (
    CMF_UPPER_LINE, CMF_LOWER_LINE,
    MFI_OVERBOUGHT, MFI_OVERSOLD, MFI_MID,
    PERCENT_B_MID, PERCENT_B_UPPER, PERCENT_B_LOWER,
    BBW_TRIGGER,
)

console = Console(width=130)


# ─────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────

def _yn(val: bool) -> Text:
    return Text("✅ YES", style="bold green") if val else Text("❌ NO", style="bold red")

def _pct_color(val: Optional[float], positive_good: bool = True) -> Text:
    if val is None:
        return Text("N/A", style="dim")
    style = "green" if (val > 0) == positive_good else "red"
    return Text(f"{val:+.2f}%", style=style)

def _float_color(val: Optional[float], threshold: float = 0,
                 positive_good: bool = True) -> Text:
    if val is None:
        return Text("N/A", style="dim")
    style = "green" if (val >= threshold) == positive_good else "red"
    return Text(f"{val:.2f}", style=style)

def _na(val, fmt: str = ".2f") -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "N/A"
    try:
        return format(val, fmt)
    except Exception:
        return str(val)


# ─────────────────────────────────────────────────────────────────
#  HEADER BANNER
# ─────────────────────────────────────────────────────────────────

def print_header():
    console.print()
    header = Panel(
        Align.center(
            "[bold bright_yellow]📈  BOLLINGER BAND SQUEEZE STRATEGY ANALYSER[/bold bright_yellow]\n"
            "[dim]Based on: Bollinger on Bollinger Bands — Method I: Volatility Breakout (Chapters 15 & 16)[/dim]\n"
            "[dim]NSE & BSE Equity Trading System  |  Short-term to Long-term Positional[/dim]"
        ),
        box=box.DOUBLE_EDGE,
        border_style="bright_yellow",
        padding=(1, 4),
    )
    console.print(header)
    console.print()


def print_section(title: str, color: str = "bright_cyan"):
    console.print(Rule(f"[bold {color}]{title}[/bold {color}]", style=color))


# ─────────────────────────────────────────────────────────────────
#  SIGNAL DASHBOARD — FOR A SINGLE STOCK
# ─────────────────────────────────────────────────────────────────

def print_signal_dashboard(sig: SignalResult, fd: Optional[FundamentalData] = None):
    """
    Full dashboard for a single stock — all 7 indicators + signals + fundamentals.
    """
    console.print()
    print_section(f"  {sig.ticker}  —  {fd.company_name if fd else sig.ticker}  ", "bright_yellow")

    # ── ACTION PANEL ──
    if sig.buy_signal:
        action_style = "bold white on green"
        icon = "🚀 BUY"
    elif sig.sell_signal:
        action_style = "bold white on red"
        icon = "🔴 SELL / EXIT"
    elif sig.hold_signal:
        action_style = "bold white on blue"
        icon = "🟢 HOLD"
    elif sig.wait_signal:
        action_style = "bold black on yellow"
        icon = "⏳ WAIT — SQUEEZE SET"
    elif sig.head_fake:
        action_style = "bold white on dark_orange"
        icon = "⚠️  HEAD FAKE — DO NOT ENTER"
    else:
        action_style = "bold white on grey35"
        icon = "⚪ MONITOR"

    console.print(
        Panel(
            f"[{action_style}]  {icon}  [/{action_style}]\n\n"
            f"{sig.action_message}",
            title=f"[bold]ACTION SIGNAL — Confidence: {sig.confidence}/100[/bold]",
            border_style="bright_white",
            padding=(1, 2),
        )
    )

    # ── TWO-COLUMN LAYOUT: INDICATORS + 5 CONDITIONS ──
    _print_indicator_panel(sig)
    _print_five_conditions(sig)

    # ── PHASE ANALYSIS ──
    _print_phase_panel(sig)

    # ── FUNDAMENTALS ──
    if fd and not fd.fetch_error:
        _print_fundamentals_panel(fd)
    elif fd and fd.fetch_error:
        is_rate_limit = "rate limit" in fd.fetch_error.lower() or "429" in fd.fetch_error or "too many" in fd.fetch_error.lower()
        if is_rate_limit:
            console.print(
                "[yellow]  ⚠  Yahoo Finance rate limit reached — fundamentals temporarily unavailable.\n"
                "     Wait 1-2 minutes and run Option 1 again to see fundamental data.[/yellow]"
            )
        else:
            console.print(f"[dim]  ⚠  Fundamental data unavailable: {fd.fetch_error[:80]}[/dim]")

    console.print()


def _print_indicator_panel(sig: SignalResult):
    """Display all 7 indicator current readings."""
    console.print()
    print_section("INDICATOR READINGS  (7 Indicators — 3 Groups)", "cyan")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan",
                  border_style="cyan", expand=False)
    table.add_column("Group",      style="dim", width=8)
    table.add_column("Indicator",  width=22)
    table.add_column("Value",      width=15, justify="right")
    table.add_column("Status",     width=35)
    table.add_column("Signal",     width=10, justify="center")

    # ── Group A — Bollinger Bands ──
    close = sig.current_price
    pct_b = sig.percent_b

    bb_status = ""
    if close > sig.bb_upper:
        bb_status = "[green]Price ABOVE upper band → BREAKOUT ↑[/green]"
    elif close < sig.bb_lower:
        bb_status = "[red]Price BELOW lower band → BREAKDOWN ↓[/red]"
    elif pct_b > PERCENT_B_UPPER:
        bb_status = "[green]Price near TOP of band (bullish)[/green]"
    elif pct_b < PERCENT_B_LOWER:
        bb_status = "[red]Price near BOTTOM of band (bearish)[/red]"
    elif pct_b > PERCENT_B_MID:
        bb_status = "[yellow]Above midline — lean bullish[/yellow]"
    else:
        bb_status = "[yellow]Below midline — lean bearish[/yellow]"

    table.add_row("A", "Bollinger Bands",
                  f"₹{close:.2f}",
                  f"Upper:₹{sig.bb_upper:.2f}  Mid:₹{sig.bb_mid:.2f}  Lower:₹{sig.bb_lower:.2f}",
                  bb_status)

    # SAR
    sar_status = (
        "[green]Dots BELOW candles = UPTREND → HOLD[/green]"
        if sig.sar_bull else
        "[red]Dots ABOVE candles = DOWNTREND → EXIT[/red]"
    )
    table.add_row("A", "Parabolic SAR",
                  f"₹{sig.sar:.2f}",
                  f"Stop Loss: ₹{sig.sar:.2f}",
                  sar_status)

    # Volume
    vol_ratio = (sig.volume / sig.vol_sma50) if sig.vol_sma50 > 0 else 0
    vol_status = (
        f"[green]{vol_ratio:.1f}x above avg — STRONG CONVICTION[/green]"
        if vol_ratio >= 1.5 else
        "[green]Above average — volume confirms[/green]"
        if vol_ratio >= 1.0 else
        f"[red]{vol_ratio:.1f}x below avg — WEAK[/red]"
    )
    table.add_row("A", "Volume + 50 SMA",
                  f"{int(sig.volume):,}",
                  f"50 SMA: {int(sig.vol_sma50):,}",
                  vol_status)

    # ── Group B — BBW ──
    bbw_pct = (sig.bbw / sig.bbw_6m_min * 100) if sig.bbw_6m_min > 0 else 100
    if sig.cond1_squeeze_on:
        bbw_status = "[bold green]🔴 SQUEEZE SET — Spring is coiled![/bold green]"
    elif sig.bbw < BBW_TRIGGER * 1.2:
        bbw_status = "[yellow]Near squeeze zone — watch closely[/yellow]"
    else:
        bbw_status = "[dim]Not in squeeze — BBW too high[/dim]"

    table.add_row("B", "BandWidth (BBW)",
                  f"{sig.bbw:.4f}",
                  f"Trigger: 0.0800  6M-Min: {sig.bbw_6m_min:.4f}",
                  bbw_status)

    # %b
    if pct_b > PERCENT_B_UPPER:
        pb_status = "[green]Above 0.80 — Bullish zone[/green]"
    elif pct_b > PERCENT_B_MID:
        pb_status = "[green]Above 0.50 — Lean bullish[/green]"
    elif pct_b < PERCENT_B_LOWER:
        pb_status = "[red]Below 0.20 — Bearish zone[/red]"
    else:
        pb_status = "[yellow]Below 0.50 — Lean bearish[/yellow]"

    table.add_row("B", "%b (Percent B)",
                  f"{pct_b:.3f}",
                  f"Levels: 0.20 / 0.50 / 0.80",
                  pb_status)

    # ── Group C — CMF ──
    cmf = sig.cmf
    if cmf > CMF_UPPER_LINE:
        cmf_status = "[bold green]Strong ACCUMULATION → Big players buying[/bold green]"
    elif cmf > 0:
        cmf_status = "[green]Mild buying — lean bullish[/green]"
    elif cmf < CMF_LOWER_LINE:
        cmf_status = "[bold red]Strong DISTRIBUTION → Big players selling[/bold red]"
    else:
        cmf_status = "[red]Mild selling — lean bearish[/red]"

    table.add_row("C", "CMF (Chaikin MF)",
                  f"{cmf:+.4f}",
                  f"Zones: -0.10 / 0 / +0.10",
                  cmf_status)

    # MFI
    mfi = sig.mfi
    if mfi > MFI_OVERBOUGHT:
        mfi_status = "[bold green]MFI > 80 — MAXIMUM FUEL → Full position[/bold green]"
    elif mfi > MFI_MID:
        mfi_status = "[green]MFI > 50 — Sufficient fuel → Enter[/green]"
    elif mfi < MFI_OVERSOLD:
        mfi_status = "[bold red]MFI < 20 — Strong selling fuel[/bold red]"
    else:
        mfi_status = "[red]MFI < 50 — Weak fuel → Skip breakout[/red]"

    table.add_row("C", "MFI (Money Flow)",
                  f"{mfi:.1f}",
                  f"Levels: 20 / 50 / 80",
                  mfi_status)

    console.print(table)


def _print_five_conditions(sig: SignalResult):
    """Display the 5-condition traffic light panel."""
    console.print()
    print_section("5-CONDITION BUY CHECKLIST  (ALL must be ✅ to BUY)", "green")

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold green",
                  border_style="green", expand=False)
    table.add_column("#",         width=4,  justify="center")
    table.add_column("Condition", width=40)
    table.add_column("Required",  width=40)
    table.add_column("Status",    width=12, justify="center")

    conditions = [
        (1, "BBW at squeeze trigger (0.08)",
         f"BBW ≤ 0.08 or at 6-month low  |  Current: {sig.bbw:.4f}",
         sig.cond1_squeeze_on),
        (2, "Price closes ABOVE upper Bollinger Band",
         f"Close > Upper Band  |  Close: ₹{sig.current_price:.2f}  Upper: ₹{sig.bb_upper:.2f}",
         sig.cond2_price_above),
        (3, "Volume GREEN and above 50-period SMA",
         f"Vol {int(sig.volume):,} > SMA {int(sig.vol_sma50):,}",
         sig.cond3_volume_ok),
        (4, "CMF above zero (ideally > +0.10)",
         f"CMF: {sig.cmf:+.4f}  |  Need: > 0.00",
         sig.cond4_cmf_positive),
        (5, "MFI above 50 and rising",
         f"MFI: {sig.mfi:.1f}  |  Need: > 50 and rising"
         + (" ✓ rising" if sig.mfi > 50 else " ✗ below 50"),
         sig.cond5_mfi_above_50),
    ]

    for num, name, required, status in conditions:
        icon = "✅ GREEN" if status else "❌ RED"
        style = "bold green" if status else "bold red"
        table.add_row(str(num), name, required, f"[{style}]{icon}[/{style}]")

    # Summary row
    count = sum([sig.cond1_squeeze_on, sig.cond2_price_above,
                 sig.cond3_volume_ok, sig.cond4_cmf_positive, sig.cond5_mfi_above_50])
    summary = f"[bold green]ALL 5 ✅ — BUY SIGNAL ACTIVE[/bold green]" \
              if count == 5 else \
              f"[bold yellow]{count}/5 conditions met — Wait for all 5[/bold yellow]"
    table.add_section()
    table.add_row("", "[bold]VERDICT[/bold]", summary, "")

    console.print(table)

    # Head Fake warning
    if sig.head_fake:
        console.print(
            Panel(
                "[bold red]⚠️  HEAD FAKE DETECTED[/bold red]\n"
                "Breakout looks suspicious. CMF/MFI/Volume are not confirming the price move.\n"
                "Wait 2-3 days. The REAL move will come in the OPPOSITE direction.\n"
                "[dim]Golden Rule: Never buy a breakout without volume above the yellow line.[/dim]",
                border_style="red",
                padding=(0, 2),
            )
        )


def _print_phase_panel(sig: SignalResult):
    """Display the 3-phase analysis panel."""
    console.print()
    print_section("SQUEEZE PHASE ANALYSIS", "bright_magenta")

    phase_styles = {
        "COMPRESSION":  ("bright_blue",   "Phase 1 — COMPRESSION", "Spring is being coiled. Low volatility. Watch CMF for direction clues."),
        "DIRECTION":    ("yellow",         "Phase 2 — DIRECTION CLUES", "Big players are positioning. CMF and MFI giving directional hints."),
        "EXPLOSION":    ("bright_red",     "Phase 3 — EXPLOSION", "Spring released! Bands expanding. This is the trade opportunity."),
        "NORMAL":       ("dim",            "No Active Squeeze", "BBW is not at trigger level. No squeeze setup present."),
        "POST-BREAKOUT":("bright_green",   "Post-Breakout Trend", "Trade in progress. Manage with SAR trailing stop."),
        "INSUFFICIENT_DATA": ("dim",       "Insufficient Data", "Need more historical data."),
    }

    style, phase_title, phase_desc = phase_styles.get(
        sig.phase, ("dim", sig.phase, "")
    )

    direction_icons = {"BULLISH": "🟢 BULLISH", "BEARISH": "🔴 BEARISH", "NEUTRAL": "⚪ NEUTRAL"}

    content = (
        f"[bold {style}]{phase_title}[/bold {style}]\n"
        f"{phase_desc}\n\n"
        f"Direction Lean : [bold]{direction_icons.get(sig.direction_lean, sig.direction_lean)}[/bold]\n"
        f"Squeeze Active : {'[bold green]YES — ' + str(sig.squeeze_days) + ' consecutive days[/bold green]' if sig.cond1_squeeze_on else '[dim]No[/dim]'}\n"
        f"SAR Direction  : {'[green]Uptrend (hold)[/green]' if sig.sar_bull else '[red]Downtrend (caution)[/red]'}"
    )

    # Exit signals
    if sig.sell_signal:
        exits = []
        if sig.exit_sar_flip:       exits.append("Signal 1: SAR Flip")
        if sig.exit_lower_band_tag: exits.append("Signal 2: Lower Band Tag")
        if sig.exit_double_neg:     exits.append("Signal 3: CMF+MFI Double Negative")
        content += f"\n\n[bold red]EXIT TRIGGERED: {' | '.join(exits)}[/bold red]"

    console.print(Panel(content, border_style=style, padding=(0, 2)))


def _score_bar(score: int, width: int = 22) -> str:
    """Render a coloured progress bar for a 0-100 score."""
    filled  = max(0, min(width, int(score / 100 * width)))
    bar     = "█" * filled + "░" * (width - filled)
    color   = "bright_green" if score >= 65 else ("yellow" if score >= 40 else "red")
    return f"[{color}]{bar}[/{color}]  [{color}]{score}/100[/{color}]"


def _fmt_cr_d(val: Optional[float], decimals: int = 2) -> str:
    """Format raw ₹ value as Crores string."""
    if val is None:
        return "N/A"
    cr = val / 1e7
    if cr >= 1_00_000:
        return f"₹{cr/1_00_000:.2f}L Cr"
    if cr >= 1_000:
        return f"₹{cr/1_000:.1f}K Cr"
    return f"₹{cr:.{decimals}f} Cr"


def _fmt_shares(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if val >= 1e9:
        return f"{val/1e9:.2f}B"
    if val >= 1e6:
        return f"{val/1e6:.2f}M"
    return f"{val:.0f}"


def _val_color(val: Optional[float], good_if_below: Optional[float] = None,
               good_if_above: Optional[float] = None, decimals: int = 2,
               prefix: str = "", suffix: str = "") -> str:
    """Return rich markup string coloured green/red based on threshold."""
    if val is None:
        return "[dim]N/A[/dim]"
    formatted = f"{prefix}{val:.{decimals}f}{suffix}"
    if good_if_below is not None:
        color = "bright_green" if val < good_if_below else "red"
    elif good_if_above is not None:
        color = "bright_green" if val >= good_if_above else "red"
    else:
        color = "white"
    return f"[{color}]{formatted}[/{color}]"


def _print_fundamentals_panel(fd: FundamentalData):
    """Display fundamental data — 7 section layout."""
    console.print()
    print_section(f"FUNDAMENTAL ANALYSIS — {fd.company_name}", "bright_blue")

    # ══════════════════════════════════════════════════════════════
    #  COMPANY HEADER
    # ══════════════════════════════════════════════════════════════
    hdr = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    hdr.add_column(style="bold dim",   width=20)
    hdr.add_column(width=28)
    hdr.add_column(style="bold dim",   width=20)
    hdr.add_column(width=28)
    hdr.add_column(style="bold dim",   width=16)
    hdr.add_column(width=18)

    w52h = f"₹{fd.week_52_high:.2f}" if fd.week_52_high else "N/A"
    w52l = f"₹{fd.week_52_low:.2f}"  if fd.week_52_low  else "N/A"
    pct  = f"{fd.week_52_pct:+.2f}% vs 52W High" if fd.week_52_pct is not None else ""
    price_str = f"[bold]₹{fd.current_price:.2f}[/bold]  [dim]{pct}[/dim]"

    hdr.add_row("Sector",       fd.sector or "—",
                "Industry",     fd.industry or "—",
                "Exchange",     fd.exchange or "—")
    hdr.add_row("Market Cap",   fd.market_cap_str,
                "Ent. Value",   fd.enterprise_value_str or "N/A",
                "Beta",         _na(fd.beta))
    hdr.add_row("Current Price", price_str,
                "52W High",     w52h,
                "52W Low",      w52l)
    console.print(hdr)

    # ══════════════════════════════════════════════════════════════
    #  SECTION 1 — VALUATION ANALYSIS + KEY RATIOS
    # ══════════════════════════════════════════════════════════════
    console.print(Rule("[bold bright_cyan]  VALUATION ANALYSIS  [/bold bright_cyan]",
                       style="bright_cyan"))

    v_score_bar = _score_bar(fd.valuation_score)
    console.print(f"  Score: {v_score_bar}")
    console.print(f"\n  {fd.valuation_analysis}\n")

    vt = Table(box=box.SIMPLE_HEAVY, show_header=True,
               header_style="bold white on dark_blue", expand=True)
    vt.add_column("VALUATION KEY RATIOS", style="bold dim", width=24)
    vt.add_column("Value",   justify="right", width=14)
    vt.add_column("Bench",   style="dim",     width=14)
    vt.add_column("",        style="bold dim", width=24)
    vt.add_column("Value",   justify="right", width=14)
    vt.add_column("Bench",   style="dim",     width=14)

    gn_str  = f"₹{fd.graham_number:.2f}"  if fd.graham_number  else "N/A"
    piv_str = _val_color(fd.price_to_intrinsic, good_if_below=1.0, decimals=3)
    pfcf    = _val_color(fd.price_to_fcf, good_if_below=20.0, decimals=2) if fd.price_to_fcf else "[dim]N/A[/dim]"

    vt.add_row(
        "P/E Ratio (TTM)",      _val_color(fd.pe_ratio, good_if_below=25, decimals=2),  "< 25 = good",
        "Forward P/E",          _val_color(fd.forward_pe, good_if_below=20, decimals=2), "< 20 = good",
    )
    vt.add_row(
        "[dim italic]Price ÷ EPS — how many years of earnings the market pays for[/dim italic]", "", "",
        "[dim italic]Based on analyst estimates — forward-looking valuation[/dim italic]", "", "",
    )
    vt.add_row(
        "Price/Book (P/B)",     _val_color(fd.pb_ratio, good_if_below=3, decimals=2),   "< 3 = ok",
        "Price/Sales (P/S)",    _val_color(fd.ps_ratio, good_if_below=3, decimals=2),   "< 3 = ok",
    )
    vt.add_row(
        "[dim italic]Price ÷ Book Value — premium over net assets[/dim italic]", "", "",
        "[dim italic]Price ÷ Revenue — what you pay per ₹ of sales[/dim italic]", "", "",
    )
    vt.add_row(
        "EV/EBITDA",            _val_color(fd.ev_ebitda, good_if_below=12, decimals=2), "< 12 = fair",
        "PEG Ratio",            _val_color(fd.peg_ratio, good_if_below=1.5, decimals=2),"< 1.5 = good",
    )
    vt.add_row(
        "[dim italic]Enterprise value ÷ EBITDA — valuation including debt[/dim italic]", "", "",
        "[dim italic]P/E ÷ Growth — < 1 means under-priced vs growth[/dim italic]", "", "",
    )
    vt.add_row(
        "Graham Number",        gn_str,                                                  "√(22.5×EPS×BV)",
        "Price / Graham No.",   piv_str,                                                 "< 1 = undervalued",
    )
    vt.add_row(
        "[dim italic]Intrinsic value estimate using Benjamin Graham formula[/dim italic]", "", "",
        "[dim italic]Current price vs Graham Number — < 1 = cheap[/dim italic]", "", "",
    )
    vt.add_row(
        "Earning Yield %",      _val_color(fd.earning_yield, good_if_above=4, decimals=2, suffix="%"), "> 4% = good",
        "Price/FCF",            pfcf,                                                    "< 20 = good",
    )
    vt.add_row(
        "[dim italic]Inverse of P/E — higher = more value per rupee[/dim italic]", "", "",
        "[dim italic]Price ÷ Free Cash — how market values cash generation[/dim italic]", "", "",
    )
    console.print(vt)
    console.print()

    # ══════════════════════════════════════════════════════════════
    #  SECTION 2 — PROFITABILITY ANALYSIS + KEY RATIOS
    # ══════════════════════════════════════════════════════════════
    console.print(Rule("[bold bright_green]  PROFITABILITY ANALYSIS  [/bold bright_green]",
                       style="bright_green"))

    p_score_bar = _score_bar(fd.profitability_score)
    console.print(f"  Score: {p_score_bar}")
    console.print(f"\n  {fd.profitability_analysis}\n")

    pt = Table(box=box.SIMPLE_HEAVY, show_header=True,
               header_style="bold white on dark_green", expand=True)
    pt.add_column("PROFITABILITY KEY RATIOS", style="bold dim", width=24)
    pt.add_column("Value",   justify="right", width=14)
    pt.add_column("Bench",   style="dim",     width=14)
    pt.add_column("",        style="bold dim", width=24)
    pt.add_column("Value",   justify="right", width=14)
    pt.add_column("Bench",   style="dim",     width=14)

    pt.add_row(
        "ROE %",                _val_color(fd.roe, good_if_above=15, decimals=2, suffix="%"),    "> 15% = strong",
        "ROA %",                _val_color(fd.roa, good_if_above=5, decimals=2, suffix="%"),     "> 5% = good",
    )
    pt.add_row(
        "[dim italic]Net Profit ÷ Shareholder Equity — return on your money[/dim italic]", "", "",
        "[dim italic]Net Profit ÷ Total Assets — efficiency of all capital[/dim italic]", "", "",
    )
    pt.add_row(
        "ROCE %",               _val_color(fd.roce, good_if_above=15, decimals=2, suffix="%"),   "> 15% = strong",
        "Gross Margin %",       _val_color(fd.gross_margin, good_if_above=25, decimals=2, suffix="%"), "> 25% = good",
    )
    pt.add_row(
        "[dim italic]EBIT ÷ Capital Employed — overall business efficiency[/dim italic]", "", "",
        "[dim italic]Revenue after COGS — higher = better pricing power[/dim italic]", "", "",
    )
    pt.add_row(
        "Operating Margin %",   _val_color(fd.operating_margin, good_if_above=12, decimals=2, suffix="%"), "> 12% = good",
        "Net Profit Margin %",  _val_color(fd.profit_margin, good_if_above=10, decimals=2, suffix="%"),    "> 10% = good",
    )
    pt.add_row(
        "[dim italic]Operating Profit ÷ Revenue — core business profitability[/dim italic]", "", "",
        "[dim italic]Net Profit ÷ Revenue — what stays after all expenses[/dim italic]", "", "",
    )
    pt.add_row(
        "EBITDA Margin %",      _val_color(fd.ebitda_margin, good_if_above=15, decimals=2, suffix="%"), "> 15% = strong",
        "EPS (TTM)",            f"₹{fd.eps_ttm:.2f}" if fd.eps_ttm else "[dim]N/A[/dim]",       "Higher = better",
    )
    pt.add_row(
        "[dim italic]EBITDA ÷ Revenue — cash profitability before D&A[/dim italic]", "", "",
        "[dim italic]Trailing 12 months earnings per share[/dim italic]", "", "",
    )
    pt.add_row(
        "EPS (Forward)",        f"₹{fd.eps_forward:.2f}" if fd.eps_forward else "[dim]N/A[/dim]", "Estimate",
        "EBITDA",               _fmt_cr_d(fd.ebitda),                                           "Higher = better",
    )
    console.print(pt)
    console.print()

    # ══════════════════════════════════════════════════════════════
    #  SECTION 3 — HIGHLIGHTS  +  SHARE HOLDING
    # ══════════════════════════════════════════════════════════════
    console.print(Rule("[bold bright_white]  HIGHLIGHTS  ✦  SHARE HOLDING  [/bold bright_white]",
                       style="white"))

    hl = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    hl.add_column(style="bold dim", width=22)
    hl.add_column(width=22)
    hl.add_column(style="bold dim", width=22)
    hl.add_column(width=22)
    hl.add_column(style="bold dim", width=22)
    hl.add_column(width=16)

    out_shares = _fmt_shares(fd.outstanding_shares)
    float_pct_str = f"{fd.float_pct:.1f}%" if fd.float_pct else "N/A"
    div_yield_str = f"{fd.dividend_yield:.2f}%" if fd.dividend_yield else "N/A"

    hl.add_row("Market Cap",        fd.market_cap_str,
               "Enterprise Value",  fd.enterprise_value_str or "N/A",
               "P/B TTM",           _val_color(fd.pb_ratio, good_if_below=3, decimals=2))
    hl.add_row("Outstanding Shares",out_shares,
               "Float %",           float_pct_str,
               "Dividend Yield",    div_yield_str)
    console.print(hl)

    # Shareholding bar (current snapshot)
    prom = fd.promoter_holding or 0.0
    fii  = fd.fii_holding      or 0.0
    pub  = fd.public_holding   or max(0.0, 100 - prom - fii)
    dii  = fd.dii_holding      or 0.0

    def _fill(pct: float, char: str, total: int = 50) -> str:
        return char * max(0, int(pct / 100 * total))

    prom_bar = f"[bold yellow]{_fill(prom,'█')}[/bold yellow]"
    fii_bar  = f"[bold cyan]{_fill(fii,'█')}[/bold cyan]"
    dii_bar  = f"[bold blue]{_fill(dii,'█')}[/bold blue]"
    pub_bar  = f"[bold white]{_fill(pub,'░')}[/bold white]"
    sh_bar   = prom_bar + fii_bar + dii_bar + pub_bar

    console.print(f"\n  [bold]SHARE HOLDING (Current)[/bold]")
    console.print(f"  {sh_bar}")
    # NOTE: yfinance only provides Institutions = FII+DII combined.
    inst_label = "Institutional (FII+DII)" if dii == 0 else "FII/Institutions"
    console.print(
        f"  [bold yellow]▐ Promoter {prom:.1f}%[/bold yellow]  "
        f"[bold cyan]▐ {inst_label} {fii:.1f}%[/bold cyan]  "
        f"[bold blue]▐ DII {dii:.1f}%[/bold blue]  "
        f"[bold white]▐ Public {pub:.1f}%[/bold white]"
    )

    # ── Shareholding Trend Table (last ~6 quarters if available) ──
    if fd.shareholding_history and len(fd.shareholding_history) > 1:
        console.print()
        sh_t = Table(box=box.SIMPLE_HEAVY, show_header=True,
                     header_style="bold white on grey23", expand=True,
                     title="[bold]SHAREHOLDING TREND (Quarterly)[/bold]")
        sh_t.add_column("Period",                       width=12, style="bold")
        sh_t.add_column("Promoter %",  justify="right", width=12)
        sh_t.add_column("",                             width=14)          # mini bar
        sh_t.add_column("Inst. %",     justify="right", width=10)
        sh_t.add_column("Public %",    justify="right", width=10)
        sh_t.add_column("Prom Δ",      justify="right", width=8)

        prev_prom = None
        for sh in reversed(fd.shareholding_history):  # oldest first
            prom_v  = sh.promoter if sh.promoter is not None else 0.0
            inst_v  = sh.fii     if sh.fii     is not None else 0.0
            pub_v   = sh.public  if sh.public  is not None else 0.0

            # mini bar for promoter
            bar_len = max(0, int(prom_v / 100 * 20))
            mini    = f"[yellow]{'█' * bar_len}{'░' * (20 - bar_len)}[/yellow]"

            # delta from previous quarter
            if prev_prom is not None:
                delta = prom_v - prev_prom
                d_str = f"[green]+{delta:.1f}[/green]" if delta > 0 else (
                         f"[red]{delta:.1f}[/red]" if delta < 0 else "[dim]0.0[/dim]")
            else:
                d_str = "[dim]—[/dim]"

            sh_t.add_row(
                sh.period,
                f"{prom_v:.1f}%",
                mini,
                f"{inst_v:.1f}%",
                f"{pub_v:.1f}%",
                d_str,
            )
            prev_prom = prom_v

        console.print(sh_t)
        console.print(
            "  [dim italic]Tip: Rising promoter holding is a confidence signal. "
            "Falling promoter + rising institutional = potential re-rating.[/dim italic]"
        )
    console.print()

    # ══════════════════════════════════════════════════════════════
    #  SECTION 4 — GROWTH KEY FIELDS
    # ══════════════════════════════════════════════════════════════
    console.print(Rule("[bold bright_magenta]  GROWTH KEY FIELDS  [/bold bright_magenta]",
                       style="bright_magenta"))

    g_score_bar = _score_bar(fd.growth_score)
    console.print(f"  Score: {g_score_bar}")
    console.print(f"\n  {fd.growth_analysis}\n")

    gt = Table(box=box.SIMPLE_HEAVY, show_header=True,
               header_style="bold white on dark_magenta", expand=True)
    gt.add_column("GROWTH METRIC",   style="bold dim", width=22)
    gt.add_column("Current Value",   justify="right",  width=18)
    gt.add_column("YoY Growth",      justify="right",  width=14)
    gt.add_column("Signal",          width=14)

    def _growth_signal(pct: Optional[float]) -> str:
        if pct is None: return "[dim]—[/dim]"
        if pct > 20:  return "[bright_green]▲ Strong[/bright_green]"
        if pct > 10:  return "[green]▲ Good[/green]"
        if pct > 0:   return "[yellow]➡ Moderate[/yellow]"
        return "[red]▼ Declining[/red]"

    gt.add_row(
        "Total Revenue",
        _fmt_cr_d(fd.total_revenue),
        _val_color(fd.revenue_growth, good_if_above=10, decimals=2, suffix="%"),
        _growth_signal(fd.revenue_growth),
    )
    gt.add_row(
        "Gross Profit",
        _fmt_cr_d(fd.gross_profit),
        "[dim]—[/dim]",
        "[dim]—[/dim]",
    )
    gt.add_row(
        "EBITDA",
        _fmt_cr_d(fd.ebitda),
        "[dim]—[/dim]",
        "[dim]—[/dim]",
    )
    gt.add_row(
        "Net Profit (Income)",
        _fmt_cr_d(fd.net_income),
        _val_color(fd.earnings_growth, good_if_above=10, decimals=2, suffix="%"),
        _growth_signal(fd.earnings_growth),
    )
    gt.add_row(
        "EPS (TTM)",
        f"₹{fd.eps_ttm:.2f}" if fd.eps_ttm else "N/A",
        "[dim]—[/dim]",
        "[dim]—[/dim]",
    )
    gt.add_row(
        "Free Cash Flow",
        _fmt_cr_d(fd.free_cash_flow),
        "[dim]—[/dim]",
        _growth_signal(fd.free_cash_flow and 15),   # positive = good signal
    )
    gt.add_row(
        "Total Assets",
        _fmt_cr_d(fd.total_assets),
        "[dim]—[/dim]",
        "[dim]—[/dim]",
    )
    console.print(gt)
    console.print()

    # ══════════════════════════════════════════════════════════════
    #  SECTION 4B — QUARTERLY RESULTS COMPARISON
    # ══════════════════════════════════════════════════════════════
    if fd.quarterly_results and len(fd.quarterly_results) >= 2:
        console.print(Rule("[bold bright_yellow]  QUARTERLY RESULTS — PERIOD COMPARISON  [/bold bright_yellow]",
                           style="bright_yellow"))

        qt = Table(box=box.SIMPLE_HEAVY, show_header=True,
                   header_style="bold white on dark_orange3", expand=True)
        qt.add_column("Quarter",       style="bold", width=12)
        qt.add_column("Revenue",       justify="right", width=16)
        qt.add_column("QoQ %",         justify="right", width=9)
        qt.add_column("Net Profit",    justify="right", width=16)
        qt.add_column("QoQ %",         justify="right", width=9)
        qt.add_column("EPS ₹",         justify="right", width=10)
        qt.add_column("QoQ %",         justify="right", width=9)
        qt.add_column("EBITDA",        justify="right", width=16)

        prev_rev = prev_ni = prev_eps = None
        # Show oldest-first for natural reading
        for qr in reversed(fd.quarterly_results):
            rev_str = _fmt_cr_d(qr.revenue) if qr.revenue else "[dim]N/A[/dim]"
            ni_str  = _fmt_cr_d(qr.net_income) if qr.net_income else "[dim]N/A[/dim]"
            eps_str = f"₹{qr.eps:.2f}" if qr.eps is not None else "[dim]N/A[/dim]"
            ebitda_str = _fmt_cr_d(qr.ebitda) if qr.ebitda else "[dim]N/A[/dim]"

            # QoQ computations (prev = earlier quarter)
            def _qoq(curr, prev_val):
                if curr and prev_val and prev_val != 0:
                    pct = (curr - prev_val) / abs(prev_val) * 100
                    color = "green" if pct > 0 else "red"
                    return f"[{color}]{pct:+.1f}%[/{color}]"
                return "[dim]—[/dim]"

            rev_qoq = _qoq(qr.revenue, prev_rev)
            ni_qoq  = _qoq(qr.net_income, prev_ni)
            eps_qoq = _qoq(qr.eps, prev_eps)

            qt.add_row(qr.period, rev_str, rev_qoq, ni_str, ni_qoq, eps_str, eps_qoq, ebitda_str)

            prev_rev = qr.revenue
            prev_ni  = qr.net_income
            prev_eps = qr.eps

        console.print(qt)

        # Auto-generate brief insight
        latest = fd.quarterly_results[0]
        prior  = fd.quarterly_results[1]
        insights = []
        if latest.revenue and prior.revenue and prior.revenue > 0:
            rev_chg = (latest.revenue - prior.revenue) / abs(prior.revenue) * 100
            direction = "grew" if rev_chg > 0 else "declined"
            insights.append(f"Revenue {direction} {abs(rev_chg):.1f}% QoQ to {_fmt_cr_d(latest.revenue)}")
        if latest.net_income and prior.net_income and prior.net_income > 0:
            ni_chg = (latest.net_income - prior.net_income) / abs(prior.net_income) * 100
            direction = "jumped" if ni_chg > 5 else ("rose" if ni_chg > 0 else "fell")
            insights.append(f"Net Profit {direction} {abs(ni_chg):.1f}% QoQ")
        if latest.eps and prior.eps and prior.eps > 0:
            eps_chg = (latest.eps - prior.eps) / abs(prior.eps) * 100
            insights.append(f"EPS moved from ₹{prior.eps:.2f} → ₹{latest.eps:.2f} ({eps_chg:+.1f}%)")

        if insights:
            console.print(f"\n  [bold]Latest ({latest.period} vs {prior.period}):[/bold] " + " · ".join(insights))
        console.print()

    # ══════════════════════════════════════════════════════════════
    #  SECTION 5 — STABILITY ANALYSIS + KEY RATIOS
    # ══════════════════════════════════════════════════════════════
    console.print(Rule("[bold bright_red]  STABILITY ANALYSIS  [/bold bright_red]",
                       style="bright_red"))

    s_score_bar = _score_bar(fd.stability_score)
    console.print(f"  Score: {s_score_bar}")
    console.print(f"\n  {fd.stability_analysis}\n")

    st = Table(box=box.SIMPLE_HEAVY, show_header=True,
               header_style="bold white on dark_red", expand=True)
    st.add_column("STABILITY KEY RATIOS", style="bold dim", width=24)
    st.add_column("Value",   justify="right", width=14)
    st.add_column("Bench",   style="dim",     width=14)
    st.add_column("",        style="bold dim", width=24)
    st.add_column("Value",   justify="right", width=14)
    st.add_column("Bench",   style="dim",     width=14)

    altman_str = _val_color(fd.altman_z_score, good_if_above=2.6, decimals=2)
    eq_str     = _fmt_cr_d(fd.shareholders_equity)
    debt_str   = _fmt_cr_d(fd.total_debt)

    st.add_row(
        "Debt / Equity",        _val_color(fd.debt_to_equity, good_if_below=1.0, decimals=2),  "< 1.0 = safe",
        "Debt / EBITDA",        _val_color(fd.debt_to_ebitda, good_if_below=3.0, decimals=2),  "< 3 = safe",
    )
    st.add_row(
        "[dim italic]Total Debt ÷ Equity — lower = less leveraged[/dim italic]", "", "",
        "[dim italic]Years to repay debt from operating cash flow[/dim italic]", "", "",
    )
    st.add_row(
        "Current Ratio",        _val_color(fd.current_ratio, good_if_above=1.5, decimals=2),   "> 1.5 = liquid",
        "Quick Ratio",          _val_color(fd.quick_ratio, good_if_above=1.0, decimals=2),     "> 1.0 = healthy",
    )
    st.add_row(
        "[dim italic]Current Assets ÷ Current Liabilities — short-term solvency[/dim italic]", "", "",
        "[dim italic]Liquid Assets ÷ Current Liabilities — no inventory[/dim italic]", "", "",
    )
    st.add_row(
        "Cash Ratio",           _val_color(fd.cash_ratio, good_if_above=0.5, decimals=2),      "> 0.5 = safe",
        "Altman Z-Score",       altman_str,                                                     "> 2.6 = safe zone",
    )
    st.add_row(
        "[dim italic]Cash ÷ Current Liabilities — purest liquidity test[/dim italic]", "", "",
        "[dim italic]Bankruptcy risk model — > 3 = strong, < 1.8 = danger[/dim italic]", "", "",
    )
    st.add_row(
        "Total Debt",           debt_str,                                                       "Lower = better",
        "Shareholders Equity",  eq_str,                                                         "Higher = better",
    )
    st.add_row(
        "[dim italic]All borrowings — loans, bonds, debentures[/dim italic]", "", "",
        "[dim italic]Net worth = Assets − Liabilities — company's own capital[/dim italic]", "", "",
    )
    st.add_row(
        "Total Cash",           _fmt_cr_d(fd.total_cash),                                       "Higher = better",
        "Payout Ratio %",       _val_color(fd.payout_ratio, good_if_below=60, decimals=2, suffix="%"), "< 60% = ok",
    )
    st.add_row(
        "[dim italic]Cash & short-term investments on hand[/dim italic]", "", "",
        "[dim italic]Dividends ÷ Net Income — how much profit is distributed[/dim italic]", "", "",
    )
    console.print(st)
    console.print()

    # ══════════════════════════════════════════════════════════════
    #  SECTION 6 — GURU NUMBERS
    # ══════════════════════════════════════════════════════════════
    console.print(Rule("[bold bright_yellow]  GURU NUMBERS  [/bold bright_yellow]",
                       style="bright_yellow"))

    guru_t = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    guru_t.add_column(style="bold dim", width=24)
    guru_t.add_column(width=16, justify="right")
    guru_t.add_column(style="dim", width=20)
    guru_t.add_column(style="bold dim", width=24)
    guru_t.add_column(width=16, justify="right")
    guru_t.add_column(style="dim", width=18)

    gn_disp    = f"₹{fd.graham_number:.2f}"    if fd.graham_number    else "N/A"
    piv_disp   = _val_color(fd.price_to_intrinsic, good_if_below=1.0, decimals=3) if fd.price_to_intrinsic else "[dim]N/A[/dim]"
    altman_d   = _val_color(fd.altman_z_score, good_if_above=2.6, decimals=2) if fd.altman_z_score else "[dim]N/A[/dim]"
    peg_d      = _val_color(fd.peg_ratio, good_if_below=1.5, decimals=2)       if fd.peg_ratio      else "[dim]N/A[/dim]"
    earn_yield = _val_color(fd.earning_yield, good_if_above=4, decimals=2, suffix="%") if fd.earning_yield else "[dim]N/A[/dim]"
    pfcf_d     = _val_color(fd.price_to_fcf, good_if_below=20, decimals=2)    if fd.price_to_fcf   else "[dim]N/A[/dim]"

    guru_t.add_row(
        "Graham Number",      gn_disp,    "√(22.5×EPS×BV)",
        "Price/Graham",       piv_disp,   "< 1 = undervalued",
    )
    guru_t.add_row(
        "Peter Lynch PEG",    peg_d,      "< 1.5 = fair",
        "Altman Z-Score",     altman_d,   "> 2.6 = safe",
    )
    guru_t.add_row(
        "Earning Yield",      earn_yield, "> 4% = attractive",
        "Price / FCF",        pfcf_d,     "< 20 = good",
    )
    console.print(guru_t)
    console.print()

    # ══════════════════════════════════════════════════════════════
    #  SECTION 7 — FUNDAMENTAL CONVICTION
    # ══════════════════════════════════════════════════════════════
    score_color = (
        "bright_green" if fd.fundamental_score >= 65 else
        "yellow"       if fd.fundamental_score >= 40 else
        "red"
    )
    ov_bar = _score_bar(fd.fundamental_score, width=30)

    score_tbl = Table(box=box.SIMPLE, show_header=False, expand=True, padding=(0, 1))
    score_tbl.add_column(style="bold dim", width=22)
    score_tbl.add_column(width=36)
    score_tbl.add_column(style="bold dim", width=20)
    score_tbl.add_column(width=30)

    score_tbl.add_row(
        "Overall Score",   f"[bold {score_color}]{fd.fundamental_score}/100[/bold {score_color}]",
        "Verdict",         f"[bold {score_color}]{fd.fundamental_verdict}[/bold {score_color}]",
    )
    score_tbl.add_row(
        "Valuation",       _score_bar(fd.valuation_score,     18),
        "Profitability",   _score_bar(fd.profitability_score, 18),
    )
    score_tbl.add_row(
        "Growth",          _score_bar(fd.growth_score,     18),
        "Stability",       _score_bar(fd.stability_score,  18),
    )

    console.print(
        Panel(
            score_tbl,
            title="[bold]FUNDAMENTAL CONVICTION BUILDER[/bold]",
            border_style=score_color,
            padding=(0, 1),
        )
    )

    console.print(
        Panel(
            fd.conviction_message,
            title="[bold]KEY CONVICTION POINTS[/bold]",
            border_style="bright_blue",
            padding=(0, 2),
        )
    )


def _make_metric_table(title: str, rows: list) -> Table:
    """Create a compact metric table (legacy helper — kept for compatibility)."""
    t = Table(title=f"[bold]{title}[/bold]", box=box.SIMPLE_HEAVY,
              show_header=True, header_style="bold white", expand=True)
    t.add_column("Metric",    style="dim", width=22)
    t.add_column("Value",     width=10, justify="right")
    t.add_column("Benchmark", style="dim", width=14)
    for metric, value, bench in rows:
        t.add_row(metric, str(value), bench)
    return t


# ─────────────────────────────────────────────────────────────────
#  SCANNER RESULTS TABLE (Multi-stock scan)
# ─────────────────────────────────────────────────────────────────

def print_scan_results(results: list[tuple[SignalResult, Optional[FundamentalData]]],
                       mode: str = "BUY"):
    """
    Print scan results for multiple stocks.
    mode: 'BUY' | 'SELL' | 'SQUEEZE' | 'ALL'
    """
    console.print()
    title_map = {
        "BUY":     "🚀 BUY SIGNALS — All 5 Conditions Met",
        "SELL":    "🔴 SELL / EXIT SIGNALS",
        "SQUEEZE": "🔵 STOCKS IN ACTIVE SQUEEZE (Phase 1 & 2)",
        "ALL":     "📊 FULL SCAN RESULTS",
    }
    print_section(title_map.get(mode, mode), "bright_yellow")

    if not results:
        console.print(f"[dim]  No {mode.lower()} signals found in this scan.[/dim]")
        return

    table = Table(
        box=box.HEAVY_HEAD, show_header=True,
        header_style="bold bright_white on dark_blue",
        border_style="bright_blue", expand=True
    )

    table.add_column("Ticker",       width=14, style="bold")
    table.add_column("Company",      width=22)
    table.add_column("Price ₹",      width=10, justify="right")
    table.add_column("Signal",       width=18, justify="center")
    table.add_column("Confidence",   width=12, justify="center")
    table.add_column("Phase",        width=18)
    table.add_column("BBW",          width=8,  justify="right")
    table.add_column("CMF",          width=8,  justify="right")
    table.add_column("MFI",          width=7,  justify="right")
    table.add_column("%b",           width=6,  justify="right")
    table.add_column("Sqz Days",     width=9,  justify="center")
    table.add_column("Lean",         width=10, justify="center")
    table.add_column("Fund. Score",  width=12, justify="center")

    for sig, fd in results:
        if sig.buy_signal:
            sig_text   = "[bold green]🚀 BUY[/bold green]"
            row_style  = ""
        elif sig.sell_signal:
            sig_text   = "[bold red]🔴 SELL[/bold red]"
            row_style  = ""
        elif sig.hold_signal:
            sig_text   = "[blue]🟢 HOLD[/blue]"
            row_style  = ""
        elif sig.wait_signal:
            sig_text   = "[yellow]⏳ WAIT[/yellow]"
            row_style  = ""
        elif sig.head_fake:
            sig_text   = "[orange1]⚠️ HEAD FAKE[/orange1]"
            row_style  = ""
        else:
            sig_text   = "[dim]⚪ MONITOR[/dim]"
            row_style  = ""

        conf_color = (
            "green" if sig.confidence >= 80 else
            "yellow" if sig.confidence >= 50 else
            "red"
        )
        conf_text = f"[{conf_color}]{sig.confidence}/100[/{conf_color}]"

        lean_icons = {
            "BULLISH": "[green]▲ Bull[/green]",
            "BEARISH": "[red]▼ Bear[/red]",
            "NEUTRAL": "[dim]◆ Neut[/dim]"
        }

        phase_short = {
            "COMPRESSION": "[blue]1-Compress[/blue]",
            "DIRECTION":   "[yellow]2-Direct[/yellow]",
            "EXPLOSION":   "[red]3-Explode[/red]",
            "NORMAL":      "[dim]Normal[/dim]",
            "POST-BREAKOUT": "[green]Running[/green]",
        }.get(sig.phase, sig.phase[:10])

        fund_score = f"{fd.fundamental_score}/100" if fd and not fd.fetch_error else "N/A"
        company = (fd.company_name[:18] + "..") if fd and len(fd.company_name) > 20 else (fd.company_name if fd else "—")

        cmf_style = "green" if sig.cmf > 0 else "red"
        mfi_style = "green" if sig.mfi > 50 else "red"

        table.add_row(
            sig.ticker,
            company,
            f"₹{sig.current_price:.2f}",
            sig_text,
            conf_text,
            phase_short,
            f"{sig.bbw:.4f}",
            f"[{cmf_style}]{sig.cmf:+.3f}[/{cmf_style}]",
            f"[{mfi_style}]{sig.mfi:.1f}[/{mfi_style}]",
            f"{sig.percent_b:.2f}",
            str(sig.squeeze_days) if sig.squeeze_days > 0 else "—",
            lean_icons.get(sig.direction_lean, "—"),
            fund_score,
        )

    console.print(table)
    console.print(f"[dim]  Showing {len(results)} stock(s)[/dim]")


# ─────────────────────────────────────────────────────────────────
#  PROGRESS BAR for scanning
# ─────────────────────────────────────────────────────────────────

def make_progress_bar() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[cyan]{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    )


def print_summary_stats(total: int, buy: int, sell: int, squeeze: int,
                        hold: int, head_fake: int):
    """Print a compact summary statistics panel."""
    console.print()
    print_section("SCAN SUMMARY", "bright_white")

    stats = Table(box=box.SIMPLE, show_header=False, expand=False)
    stats.add_column(width=22, style="dim")
    stats.add_column(width=12, justify="right")
    stats.add_column(width=22, style="dim")
    stats.add_column(width=12, justify="right")

    stats.add_row(
        "Total Stocks Scanned:", f"[bold]{total}[/bold]",
        "Buy Signals:",           f"[bold green]{buy}[/bold green]"
    )
    stats.add_row(
        "Stocks in Squeeze:",   f"[bold blue]{squeeze}[/bold blue]",
        "Sell/Exit Signals:",    f"[bold red]{sell}[/bold red]"
    )
    stats.add_row(
        "Hold Signals:",        f"[bold cyan]{hold}[/bold cyan]",
        "Head Fake Warnings:",   f"[bold orange1]{head_fake}[/bold orange1]"
    )
    console.print(stats)


def print_error(message: str):
    console.print(f"[bold red]ERROR:[/bold red] {message}")


def print_info(message: str):
    console.print(f"[bold cyan]ℹ[/bold cyan]  {message}")


def print_success(message: str):
    console.print(f"[bold green]✅[/bold green]  {message}")


def print_warning(message: str):
    console.print(f"[bold yellow]⚠️[/bold yellow]  {message}")
