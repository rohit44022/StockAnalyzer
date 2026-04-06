#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║        BOLLINGER BAND SQUEEZE STRATEGY — MAIN APPLICATION           ║
║                                                                      ║
║  Based on: Bollinger on Bollinger Bands — John Bollinger CFA CMT    ║
║  Method I: Volatility Breakout — Chapters 15 & 16                   ║
║                                                                      ║
║  Features:                                                           ║
║  • Single stock analysis with full 7-indicator dashboard            ║
║  • Full NSE/BSE market scan for squeeze opportunities               ║
║  • Buy / Hold / Sell / Wait signals with plain-English explanations ║
║  • Head-fake detection with golden filters                          ║
║  • Fundamental analysis for conviction building                     ║
║  • Historical data downloader (fixed)                               ║
╚══════════════════════════════════════════════════════════════════════╝

Run:  python main.py
"""

import sys
import os
import glob
import pandas as pd
from datetime import date, timedelta

# ── Ensure the project root is on the Python path ──
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from rich.prompt import Prompt, Confirm
from rich.console import Console
from rich import box
from rich.table import Table
from rich.panel import Panel
from rich.align import Align

from bb_squeeze.config import CSV_DIR
from bb_squeeze.display import (
    console, print_header, print_section,
    print_signal_dashboard, print_info,
    print_error, print_success, print_warning,
)
from bb_squeeze.data_loader import (
    normalise_ticker, load_stock_data, get_all_tickers_from_csv,
    download_all_historical_data,
)
from bb_squeeze.indicators import compute_all_indicators
from bb_squeeze.signals import analyze_signals
from bb_squeeze.fundamentals import fetch_fundamentals
from bb_squeeze.scanner import SqueezeScanner, analyze_single_ticker


# ─────────────────────────────────────────────────────────────────
#  TICKERS LIST (from historical_data.py — cleaned)
# ─────────────────────────────────────────────────────────────────
ALL_TICKERS = [
    '20MICRONS.NS','21STCENMGM.NS','360ONE.NS','3IINFOLTD.NS','3MINDIA.NS',
    '3PLAND.NS','5PAISA.NS','63MOONS.NS','A2ZINFRA.NS','AAATECH.NS',
    'AADHARHFC.NS','AAREYDRUGS.NS','AARON.NS','AARTECH.NS','AARTIDRUGS.NS',
    'AARTIIND.NS','AARTIPHARM.NS','AARTISURF.NS','AARVEEDEN.NS','AARVI.NS',
    'AAVAS.NS','ABAN.NS','ABB.NS','ABBOTINDIA.NS','ABCAPITAL.NS','ABFRL.NS',
    'ABMINTLLTD.NS','ABSLAMC.NS','ACC.NS','ACCELYA.NS','ACCURACY.NS',
    'ACE.NS','ACEINTEG.NS','ACI.NS','ACL.NS','ACLGATI.NS','ADANIENSOL.NS',
    'ADANIENT.NS','ADANIGREEN.NS','ADANIPORTS.NS','ADANIPOWER.NS','ADFFOODS.NS',
    'ADL.NS','ADORWELD.NS','ADROITINFO.NS','ADSL.NS','ADVANIHOTR.NS',
    'ADVENZYMES.NS','AEGISLOG.NS','AEROFLEX.NS','AETHER.NS','AFFLE.NS',
    'AGARIND.NS','AGI.NS','AGRITECH.NS','AGROPHOS.NS','AGSTRA.NS',
    'AHL.NS','AHLADA.NS','AHLEAST.NS','AHLUCONT.NS','AIAENG.NS',
    'AIIL.NS','AIRAN.NS','AIROLAM.NS','AJANTPHARM.NS','AJMERA.NS',
    'AJOONI.NS','AKASH.NS','AKG.NS','AKI.NS','AKSHAR.NS','AKSHARCHEM.NS',
    'AKSHOPTFBR.NS','AKZOINDIA.NS','ALANKIT.NS','ALBERTDAVD.NS',
    'ALEMBICLTD.NS','ALICON.NS','ALKALI.NS','ALKEM.NS','ALKYLAMINE.NS',
    'ALLCARGO.NS','ALLSEC.NS','ALMONDZ.NS','ALOKINDS.NS','ALPA.NS',
    'ALPHAGEO.NS','ALPSINDUS.NS','AMBER.NS','AMBIKCO.NS','AMBUJACEM.NS',
    'AMDIND.NS','AMIORG.NS','AMRUTANJAN.NS','ANANDRATHI.NS','ANANTRAJ.NS',
    'ANDHRSUGAR.NS','ANGELONE.NS','ANKITMETAL.NS','ANUP.NS','APARINDS.NS',
    'APLAPOLLO.NS','APLLTD.NS','APOLLOHOSP.NS','APOLLOPIPE.NS','APOLLOTYRE.NS',
    'ASTRAL.NS','ATGL.NS','ATUL.NS','AUBANK.NS','AUROPHARMA.NS',
    'AXISBANK.NS','BAJAJ-AUTO.NS','BAJAJFINSV.NS','BAJAJHLDNG.NS',
    'BAJFINANCE.NS','BALKRISIND.NS','BANDHANBNK.NS','BANKBARODA.NS',
    'BANKINDIA.NS','BATAINDIA.NS','BEL.NS','BEML.NS','BERGEPAINT.NS',
    'BHARATFORG.NS','BHARTIARTL.NS','BHEL.NS','BIOCON.NS','BIRLACORPN.NS',
    'BLUEDART.NS','BLUESTARCO.NS','BOSCHLTD.NS','BPCL.NS','BRIGADE.NS',
    'BRITANNIA.NS','BSE.NS','BSOFT.NS','CAMS.NS','CANBK.NS',
    'CANFINHOME.NS','CARBORUNIV.NS','CARERATING.NS','CASTROLIND.NS',
    'CDSL.NS','CEATLTD.NS','CESC.NS','CGPOWER.NS','CHALET.NS',
    'CHAMBLFERT.NS','CHOLAFIN.NS','CIPLA.NS','COALINDIA.NS','COFORGE.NS',
    'COLPAL.NS','CONCOR.NS','COROMANDEL.NS','CRAFTSMAN.NS','CREDITACC.NS',
    'CRISIL.NS','CROMPTON.NS','CUMMINSIND.NS','CYIENT.NS','DABUR.NS',
    'DALBHARAT.NS','DATAPATTNS.NS','DBCORP.NS','DCBBANK.NS','DCMSHRIRAM.NS',
    'DEEPAKFERT.NS','DEEPAKNTR.NS','DELHIVERY.NS','DELTACORP.NS',
    'DEVYANI.NS','DIVISLAB.NS','DIXON.NS','DLF.NS','DMART.NS',
    'DODLA.NS','DOMS.NS','DREAMFOLKS.NS','DRREDDY.NS','ECLERX.NS',
    'EDELWEISS.NS','EICHERMOT.NS','EIDPARRY.NS','ELECON.NS','ELGIEQUIP.NS',
    'EMAMILTD.NS','EMKAY.NS','ENDURANCE.NS','ENGINERSIN.NS','ENIL.NS',
    'ESCORTS.NS','ETHOSLTD.NS','EVEREADY.NS','EXIDEIND.NS','EXPLEOSOL.NS',
    'FEDERALBNK.NS','FEDFINA.NS','FIEMIND.NS','FINEORG.NS','FIVESTAR.NS',
    'FLUOROCHEM.NS','FORCEMOT.NS','FORTIS.NS','GABRIEL.NS','GAEL.NS',
    'GAIL.NS','GALAXYSURF.NS','GRAVITA.NS','GRINDWELL.NS','GRSE.NS',
    'GSFC.NS','GSPL.NS','HAL.NS','HAPPSTMNDS.NS','HAVELLS.NS',
    'HBLPOWER.NS','HCLTECH.NS','HDFCAMC.NS','HDFCBANK.NS','HDFCLIFE.NS',
    'HEG.NS','HEROMOTOCO.NS','HFCL.NS','HIKAL.NS','HIL.NS',
    'HINDALCO.NS','HINDCOPPER.NS','HINDPETRO.NS','HINDUNILVR.NS',
    'HINDZINC.NS','HUDCO.NS','ICICIBANK.NS','ICICIGI.NS','ICICIPRULI.NS',
    'IDFC.NS','IDFCFIRSTB.NS','IEX.NS','IGL.NS','IIFL.NS',
    'INDHOTEL.NS','INDIACEM.NS','INDIAMART.NS','INDIANB.NS','INDIGO.NS',
    'INDIGOPNTS.NS','INDUSINDBK.NS','INDUSTOWER.NS','INFY.NS','INTELLECT.NS',
    'IOB.NS','IOC.NS','IPCALAB.NS','IRCTC.NS','IRFC.NS',
    'ISEC.NS','ITC.NS','ITDCEM.NS','J&KBANK.NS','JAIBALAJI.NS',
    'JBCHEPHARM.NS','JBMA.NS','JKCEMENT.NS','JKLAKSHMI.NS','JKPAPER.NS',
    'JKTYRE.NS','JMFINANCIL.NS','JSWENERGY.NS','JSWINFRA.NS','JSWSTEEL.NS',
    'JUBLFOOD.NS','JUBLINGREA.NS','JUBLPHARMA.NS','KAJARIACER.NS',
    'KALYANKJIL.NS','KANSAINER.NS','KARURVYSYA.NS','KAYNES.NS',
    'KEC.NS','KEI.NS','KFINTECH.NS','KIMS.NS','KIOCL.NS','KNRCON.NS',
    'KOLTEPATIL.NS','KOTAKBANK.NS','KPIGREEN.NS','KPIL.NS','KPITTECH.NS',
    'KPRMILL.NS','KRBL.NS','LAURUSLABS.NS','LALPATHLAB.NS','LATENTVIEW.NS',
    'LEMONTREE.NS','LICHSGFIN.NS','LICI.NS','LINCOL.NS','LINDEINDIA.NS',
    'LLOYDSENGG.NS','LODHA.NS','LT.NS','LTF.NS','LTFOODS.NS',
    'LTIM.NS','LTTS.NS','LUPIN.NS','LUXIND.NS','M&M.NS','M&MFIN.NS',
    'MANAPPURAM.NS','MANKIND.NS','MANYAVAR.NS','MARICO.NS','MARUTI.NS',
    'MASTEK.NS','MAXHEALTH.NS','MAZDOCK.NS','MCX.NS','MEDANTA.NS',
    'METROPOLIS.NS','MFSL.NS','MGL.NS','MIDHANI.NS','MINDACORP.NS',
    'MOIL.NS','MOLDTKPAC.NS','MOTHERSON.NS','MOTILALOFS.NS','MPHASIS.NS',
    'MRF.NS','MRPL.NS','MUTHOOTFIN.NS','NATCOPHARM.NS','NATIONALUM.NS',
    'NAUKRI.NS','NAVINFLUOR.NS','NAZARA.NS','NBCC.NS','NCC.NS',
    'NESTLEIND.NS','NETWEB.NS','NETWORK18.NS','NEULANDLAB.NS','NEWGEN.NS',
    'NHPC.NS','NIITLTD.NS','NILKAMAL.NS','NLCINDIA.NS','NMDC.NS',
    'NOCIL.NS','NRBBEARING.NS','NTPC.NS','NUCLEUS.NS','NUVOCO.NS',
    'NYKAA.NS','OBEROIRLTY.NS','OFSS.NS','OIL.NS','OLECTRA.NS',
    'OMAXE.NS','ONGC.NS','PAGEIND.NS','PAISALO.NS','PANACEABIO.NS',
    'PAYTM.NS','PCBL.NS','PEL.NS','PERSISTENT.NS','PETRONET.NS',
    'PFC.NS','PFIZER.NS','PIDILITIND.NS','PIIND.NS','PNB.NS',
    'PNBHOUSING.NS','PNCINFRA.NS','POLICYBZR.NS','POLYCAB.NS','POLYMED.NS',
    'POONAWALLA.NS','POWERGRID.NS','POWERMECH.NS','PRAJIND.NS','PRESTIGE.NS',
    'PRINCEPIPE.NS','PRUDENT.NS','PVRINOX.NS','RAILTEL.NS','RAIN.NS',
    'RAINBOW.NS','RAJESHEXPO.NS','RAMCOCEM.NS','RAMCOSYS.NS','RATNAMANI.NS',
    'RAYMOND.NS','RBLBANK.NS','RECLTD.NS','REDINGTON.NS','RELAXO.NS',
    'RELIANCE.NS','RITES.NS','RVNL.NS','SBICARD.NS','SBILIFE.NS',
    'SBIN.NS','SCHAEFFLER.NS','SCHNEIDER.NS','SEAMECLTD.NS','SENCO.NS',
    'SHAKTIPUMP.NS','SHREECEM.NS','SHRIRAMFIN.NS','SIEMENS.NS','SJVN.NS',
    'SKFINDIA.NS','SOBHA.NS','SOLARA.NS','SOLARINDS.NS','SONACOMS.NS',
    'SONATSOFTW.NS','SPANDANA.NS','SPARC.NS','SRF.NS','STARCEMENT.NS',
    'STARHEALTH.NS','SUNCLAY.NS','SUNDARMFIN.NS','SUNPHARMA.NS','SUNTV.NS',
    'SUPRAJIT.NS','SUPREMEIND.NS','SURYODAY.NS','SUZLON.NS','SYNGENE.NS',
    'SYRMA.NS','TATACHEM.NS','TATACOMM.NS','TATACONSUM.NS','TATAELXSI.NS',
    'TATAMOTORS.NS','TATAPOWER.NS','TATASTEEL.NS','TATATECH.NS',
    'TCS.NS','TEAMLEASE.NS','TECHM.NS','TEGA.NS','TEJASNET.NS',
    'THERMAX.NS','THYROCARE.NS','TIINDIA.NS','TITAGARH.NS','TITAN.NS',
    'TORNTPHARM.NS','TORNTPOWER.NS','TRENT.NS','TRIDENT.NS','TRIVENI.NS',
    'TTKPRESTIG.NS','TVSMOTOR.NS','UBL.NS','UCOBANK.NS','UFLEX.NS',
    'UJJIVANSFB.NS','ULTRACEMCO.NS','UNIONBANK.NS','UNIPARTS.NS',
    'UNOMINDA.NS','UPL.NS','USHAMART.NS','UTIAMC.NS','UTKARSHBNK.NS',
    'VBL.NS','VEDL.NS','VENKEYS.NS','VGUARD.NS','VINATIORGA.NS',
    'VIPCLOTHNG.NS','VMART.NS','VOLTAMP.NS','VOLTAS.NS','VRLLOG.NS',
    'VSTL.NS','VSTTILLERS.NS','WABAG.NS','WIPRO.NS','WONDERLA.NS',
    'XCHANGING.NS','XELPMOC.NS','YESBANK.NS','ZAGGLE.NS','ZEEL.NS',
    'ZENSARTECH.NS','ZOMATO.NS','ZYDUSLIFE.NS','ZYDUSWELL.NS',
]



# ─────────────────────────────────────────────────────────────────
#  STARTUP: AUTO DATA FRESHNESS CHECK
# ─────────────────────────────────────────────────────────────────

STALENESS_DAYS = 4   # re-download if last data is older than this many calendar days

def _get_data_staleness() -> tuple[int, str | None]:
    """
    Check how stale the local CSV data is.
    Samples up to 20 random CSVs and returns (days_old, last_date_str).
    Returns (999, None) if no CSVs found.
    """
    csv_files = glob.glob(os.path.join(CSV_DIR, "*.csv"))
    if not csv_files:
        return 999, None

    import random
    sample = random.sample(csv_files, min(20, len(csv_files)))
    last_dates = []
    for f in sample:
        try:
            df = pd.read_csv(f, usecols=["Date"])
            if df.empty:
                continue
            last_dates.append(pd.to_datetime(df["Date"].iloc[-1]))
        except Exception:
            continue

    if not last_dates:
        return 999, None

    latest = max(last_dates)
    today  = pd.Timestamp(date.today())
    days_old = (today - latest).days
    return days_old, latest.strftime("%Y-%m-%d")


def check_and_update_data(force: bool = False) -> None:
    """
    Called at startup. Checks if historical data is up-to-date.
    If stale (> STALENESS_DAYS days old), asks the user and downloads.
    If no data at all, downloads automatically without asking.
    """
    days_old, last_date = _get_data_staleness()
    today_str = date.today().strftime("%Y-%m-%d")

    # ── No data at all → download automatically ──
    if days_old == 999:
        console.print(
            "\n[bold bright_red]⚠  No historical data found in stock_csv/.[/bold bright_red]\n"
            "[dim]   Downloading all historical data now — this is needed before analysis.[/dim]\n"
        )
        _run_auto_download()
        return

    # ── Data is fresh enough → skip ──
    if days_old <= STALENESS_DAYS:
        console.print(
            f"[dim]  ✓ Historical data is up-to-date  "
            f"(last date: [bold]{last_date}[/bold]  |  today: {today_str})[/dim]\n"
        )
        return

    # ── Data is stale → ask user ──
    console.print(
        f"\n[bold yellow]⚠  Historical data is [bold red]{days_old} days old[/bold red][/bold yellow]"
        f"  (last date: [bold]{last_date}[/bold]  |  today: [bold]{today_str}[/bold])\n"
        f"[dim]   It is recommended to update before scanning for signals.[/dim]\n"
    )
    if Confirm.ask("  [bold cyan]Update historical data now before proceeding?[/bold cyan]", default=True):
        _run_auto_download()
    else:
        console.print("[dim]  Skipping update — using existing data.[/dim]\n")


def _run_auto_download() -> None:
    """Download all historical data with progress shown."""
    try:
        from historical_data import get_historical_data, START_DATE, END_DATE, TICKERS
    except ImportError:
        print_error("Could not import historical_data.py — make sure it is in the same folder.")
        return

    console.print(
        f"[bold bright_cyan]  Downloading historical data for {len(TICKERS)} tickers ...[/bold bright_cyan]\n"
        f"[dim]  Period: {START_DATE} → {END_DATE}[/dim]\n"
        f"[dim]  Output: {CSV_DIR}[/dim]\n"
    )
    get_historical_data(
        tickers       = TICKERS,
        start_date    = START_DATE,
        end_date      = END_DATE,
        save_path     = CSV_DIR,
        skip_existing = True,   # smart-skip: only skips truly up-to-date files
        retry_once    = True,
    )
    console.print("[bold bright_green]  ✓ Data update complete.[/bold bright_green]\n")


# ─────────────────────────────────────────────────────────────────
#  MENU
# ─────────────────────────────────────────────────────────────────

MENU = """
[bold bright_yellow]📊 MAIN MENU[/bold bright_yellow]

  [bold cyan]1[/bold cyan]  →  Analyze a specific stock (Enter ticker name)
  [bold cyan]2[/bold cyan]  →  Scan ALL stocks — Show BUY signals
  [bold cyan]3[/bold cyan]  →  Scan ALL stocks — Show SELL / EXIT signals
  [bold cyan]4[/bold cyan]  →  Scan ALL stocks — Show SQUEEZE stocks (Phase 1 & 2)
  [bold cyan]5[/bold cyan]  →  Scan ALL stocks — Show COMPLETE report
  [bold cyan]6[/bold cyan]  →  Download / Update historical data
  [bold cyan]7[/bold cyan]  →  Help — How to use this software
  [bold cyan]0[/bold cyan]  →  Exit
"""


def print_menu():
    console.print(Panel(MENU, box=box.ROUNDED, border_style="bright_yellow", padding=(0, 2)))


# ─────────────────────────────────────────────────────────────────
#  OPTION 1: SINGLE STOCK ANALYSIS
# ─────────────────────────────────────────────────────────────────

def run_single_stock():
    console.print()
    ticker_raw = Prompt.ask(
        "[bold cyan]Enter stock ticker (e.g. RELIANCE, RELIANCE.NS, HDFC, TCS)[/bold cyan]"
    ).strip()

    if not ticker_raw:
        print_error("No ticker entered.")
        return

    ticker = normalise_ticker(ticker_raw)
    print_info(f"Analysing [bold]{ticker}[/bold] ...")

    # Load data
    df = load_stock_data(ticker, csv_dir=CSV_DIR)

    if df is None:
        print_warning(f"No local data for {ticker}. Fetching from Yahoo Finance...")
        from bb_squeeze.data_loader import fetch_live_data
        df = fetch_live_data(ticker)

    if df is None:
        print_error(
            f"Could not load data for {ticker}.\n"
            f"  → Check ticker spelling (use NSE format: RELIANCE.NS)\n"
            f"  → Or run Option 6 to download historical data first."
        )
        return

    # Compute indicators
    df = compute_all_indicators(df)

    # Generate signals
    sig = analyze_signals(ticker, df)

    # Fetch fundamentals (with retry on rate limit)
    print_info("Fetching fundamental data from Yahoo Finance...")
    fd = None
    max_fund_attempts = 3
    for attempt in range(max_fund_attempts):
        try:
            fd = fetch_fundamentals(ticker)
            if fd.fetch_error:
                is_rate_limit = (
                    "rate limit" in fd.fetch_error.lower()
                    or "429" in fd.fetch_error
                    or "too many" in fd.fetch_error.lower()
                )
                if is_rate_limit and attempt < max_fund_attempts - 1:
                    wait_secs = (attempt + 1) * 15
                    print_warning(
                        f"Yahoo Finance rate limit — waiting {wait_secs}s before retry "
                        f"(attempt {attempt + 1}/{max_fund_attempts})..."
                    )
                    import time as _time; _time.sleep(wait_secs)
                    continue
            break   # success (or non-rate-limit error)
        except Exception as exc:
            fd = None
            break

    # Display full dashboard
    print_signal_dashboard(sig, fd)

    # Offer to see raw indicator values
    show_raw = Confirm.ask("\n[dim]Show last 5 days of raw indicator values?[/dim]", default=False)
    if show_raw:
        _show_raw_data(df)

    # ── Export to Excel ──────────────────────────────────────────
    if Confirm.ask("\n[dim]Export this analysis to Excel?[/dim]", default=False):
        _do_export([(sig, fd)], mode="SINGLE", single_ticker=ticker)


def _show_raw_data(df):
    """Print last 5 rows of indicator data."""
    cols = ["Close", "BB_Upper", "BB_Mid", "BB_Lower", "BBW", "Percent_B",
            "SAR", "SAR_Bull", "Volume", "Vol_SMA50", "CMF", "MFI", "Squeeze_ON"]
    display_cols = [c for c in cols if c in df.columns]
    last5 = df[display_cols].tail(5)

    table = Table(title="Last 5 Days — Raw Indicator Values",
                  box=box.SIMPLE_HEAVY, show_header=True,
                  header_style="bold cyan")
    table.add_column("Date", width=12)
    for col in display_cols:
        table.add_column(col[:12], width=13, justify="right")

    for idx, row in last5.iterrows():
        row_vals = [str(idx)[:10]]
        for col in display_cols:
            val = row[col]
            if isinstance(val, bool):
                row_vals.append("✅" if val else "❌")
            elif isinstance(val, float):
                row_vals.append(f"{val:.4f}")
            else:
                row_vals.append(str(val))
        table.add_row(*row_vals)

    console.print(table)


# ─────────────────────────────────────────────────────────────────
#  OPTIONS 2-5: SCANNER
# ─────────────────────────────────────────────────────────────────

def run_scan(mode: str = "ALL"):
    """Run the full market scanner across ALL stocks in stock_csv/."""
    tickers_available = get_all_tickers_from_csv(CSV_DIR)

    if not tickers_available:
        print_warning("No CSV files found in stock_csv directory.")
        if Confirm.ask("Download historical data now?", default=True):
            run_download()
            tickers_available = get_all_tickers_from_csv(CSV_DIR)

    if not tickers_available:
        print_error("Cannot scan — no data available.")
        return

    mode_labels = {
        "BUY":     "🚀 BUY Signals",
        "SELL":    "🔴 SELL / EXIT Signals",
        "SQUEEZE": "🔵 SQUEEZE Stocks (Phase 1 & 2)",
        "ALL":     "📊 Full Market Report",
    }
    console.print(
        Panel(
            f"[bold bright_cyan]Scan Mode  :[/bold bright_cyan]  {mode_labels.get(mode, mode)}\n"
            f"[bold bright_cyan]Universe   :[/bold bright_cyan]  [bold]{len(tickers_available)}[/bold] NSE stocks (all CSVs in stock_csv/)\n"
            f"[bold bright_cyan]Data Dir   :[/bold bright_cyan]  {CSV_DIR}\n"
            f"[bold bright_cyan]Threads    :[/bold bright_cyan]  16 parallel workers",
            title="[bold bright_yellow]MARKET SCAN PARAMETERS[/bold bright_yellow]",
            border_style="bright_yellow",
            padding=(0, 2),
        )
    )

    ask_fund = Confirm.ask(
        "\n[dim]Fetch fundamental scores for signal stocks? (slower — adds conviction scores)[/dim]",
        default=False
    )

    scanner = SqueezeScanner(
        csv_dir=CSV_DIR,
        max_workers=16,                        # 16 threads for faster 1983-stock scan
        fetch_fundamentals_for_signals=False   # scan without fundamentals for speed
    )

    scanner.scan(tickers_available)

    # If user wants fundamentals, fetch for signal stocks only
    if ask_fund:
        _enrich_fundamentals(scanner, mode)

    scanner.print_report(mode=mode)

    # ── Export to Excel ──────────────────────────────────────────
    # Build the export list based on which mode was selected
    mode_results = {
        "BUY":     scanner.buy_signals,
        "SELL":    scanner.sell_signals,
        "SQUEEZE": scanner.squeeze_only,
        "ALL":     scanner.all_results,
    }
    export_data = mode_results.get(mode, scanner.all_results)
    if export_data and Confirm.ask("\n[dim]Export scan results to Excel?[/dim]", default=False):
        _do_export(export_data, mode=mode)


def _do_export(results, mode: str, single_ticker: str = ""):
    """Export results to a colour-coded Excel workbook and report the file path."""
    try:
        from bb_squeeze.exporter import export_to_excel
        filepath = export_to_excel(
            results=results,
            mode=mode,
            output_dir=ROOT,
            single_ticker=single_ticker,
        )
        print_success(
            f"Excel file saved → [bold]{os.path.basename(filepath)}[/bold]\n"
            f"  Location: {filepath}"
        )
    except Exception as exc:
        print_error(f"Export failed: {exc}")


def _enrich_fundamentals(scanner: SqueezeScanner, mode: str):
    """Fetch fundamentals only for signal stocks."""
    targets = []
    if mode in ("BUY", "ALL"):
        targets.extend(scanner.buy_signals)
    if mode in ("SELL", "ALL"):
        targets.extend(scanner.sell_signals)
    if mode in ("SQUEEZE", "ALL"):
        targets.extend(scanner.squeeze_only[:20])

    if not targets:
        return

    print_info(f"Fetching fundamentals for {len(targets)} signal stocks...")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(fetch_fundamentals, sig.ticker): i
                   for i, (sig, _) in enumerate(targets)}
        for fut, idx in futures.items():
            try:
                fd = fut.result(timeout=15)
                sig, _ = targets[idx]
                targets[idx] = (sig, fd)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────
#  OPTION 6: DOWNLOAD HISTORICAL DATA
# ─────────────────────────────────────────────────────────────────

def run_download():
    console.print()
    print_section("HISTORICAL DATA DOWNLOAD", "bright_blue")

    console.print(
        f"[dim]  Data will be saved to:[/dim] [bold]{CSV_DIR}[/bold]\n"
        f"[dim]  Total tickers to download:[/dim] [bold]{len(ALL_TICKERS)}[/bold]\n"
    )

    skip = Confirm.ask(
        "Skip tickers that already have local CSV files? (recommended)", default=True
    )
    start = Confirm.ask("Start download now?", default=True)

    if not start:
        return

    results = download_all_historical_data(
        tickers=ALL_TICKERS,
        save_path=CSV_DIR,
        skip_existing=skip,
    )

    print_success(
        f"Download complete — "
        f"Success: {len(results['success'])} | "
        f"Failed: {len(results['failed'])} | "
        f"Skipped: {len(results['skipped'])}"
    )

    if results["failed"]:
        console.print(f"[dim]Failed tickers: {', '.join(results['failed'][:20])}...[/dim]")


# ─────────────────────────────────────────────────────────────────
#  OPTION 7: HELP
# ─────────────────────────────────────────────────────────────────

def show_help():
    help_text = """
[bold bright_yellow]HOW TO USE THIS SOFTWARE[/bold bright_yellow]

[bold cyan]QUICK START[/bold cyan]
  1. Run [bold]Option 6[/bold] first to download historical data for all stocks.
     This needs to be done only once (or when you want to update data).

  2. Use [bold]Option 1[/bold] to analyse any specific stock by ticker name.
     Example: Enter  RELIANCE  or  RELIANCE.NS  or  TCS  or  HDFC

  3. Use [bold]Options 2-5[/bold] to scan the entire market for signals.

[bold cyan]UNDERSTANDING SIGNALS[/bold cyan]

  🚀 [bold green]BUY[/bold green]
     All 5 conditions are met. Enter tomorrow at market open.
     Stop Loss = Parabolic SAR value shown.

  🟢 [bold blue]HOLD[/bold blue]
     You are in a trade. Trend is intact. Stay in.
     SAR dots are below candles. Keep trailing your stop loss.

  🔴 [bold red]SELL / EXIT[/bold red]
     ONE of the 3 exit signals has triggered. Exit tomorrow morning.
     • Signal 1: Price closed below SAR dot (primary exit)
     • Signal 2: Price touched lower Bollinger Band (max profit exit)
     • Signal 3: CMF < 0 AND MFI < 50 (early warning exit)

  ⏳ [bold yellow]WAIT[/bold yellow]
     Squeeze is SET but breakout not confirmed yet.
     Watch it daily. The spring is coiling.

  ⚠️  [bold orange1]HEAD FAKE[/bold orange1]
     Price broke out but indicators are contradicting it.
     DO NOT ENTER. Wait 2-3 days for the REAL move.

[bold cyan]5 BUY CONDITIONS (ALL must be ✅)[/bold cyan]
  1. BBW at or below 0.08 trigger (squeeze SET)
  2. Price candle CLOSES above upper Bollinger Band
  3. Volume bar GREEN and ABOVE the 50-period SMA line
  4. CMF above zero (big players quietly accumulating)
  5. MFI above 50 and rising (breakout has fuel)

[bold cyan]3 EXIT SIGNALS (ONE is enough)[/bold cyan]
  1. Parabolic SAR flip — price closes below SAR dot
  2. Price tags lower Bollinger Band
  3. CMF drops below zero AND MFI drops below 50 (double negative)

[bold cyan]INDICATORS USED (7 total)[/bold cyan]
  Group A (Main Chart): Bollinger Bands, Parabolic SAR, Volume + 50 SMA
  Group B (Squeeze):    BandWidth (BBW), %b (Percent B)
  Group C (Direction):  CMF (Chaikin Money Flow), MFI (Money Flow Index)

[bold dim]Source: Bollinger on Bollinger Bands, John Bollinger CFA CMT, McGraw-Hill 2002[/bold dim]
[bold dim]Method I: Volatility Breakout — Chapters 15 & 16[/bold dim]
"""
    console.print(Panel(help_text, box=box.ROUNDED, border_style="bright_yellow", padding=(1, 3)))


# ─────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────

def main():
    print_header()
    check_and_update_data()   # ← auto-check data freshness on every startup

    while True:
        print_menu()
        choice = Prompt.ask(
            "[bold bright_yellow]Enter your choice[/bold bright_yellow]",
            choices=["0", "1", "2", "3", "4", "5", "6", "7"],
            default="1",
        )

        if choice == "0":
            console.print("\n[bold bright_yellow]Goodbye! Happy Trading! 📈[/bold bright_yellow]\n")
            break

        elif choice == "1":
            run_single_stock()

        elif choice == "2":
            run_scan(mode="BUY")

        elif choice == "3":
            run_scan(mode="SELL")

        elif choice == "4":
            run_scan(mode="SQUEEZE")

        elif choice == "5":
            run_scan(mode="ALL")

        elif choice == "6":
            run_download()

        elif choice == "7":
            show_help()

        # Pause before showing menu again
        console.print()
        Prompt.ask("[dim]Press ENTER to return to main menu[/dim]", default="")


if __name__ == "__main__":
    main()
