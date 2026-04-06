"""
Trade P&L Calculator for Indian Equity Markets — Zerodha & Dhan
================================================================
All charges, taxes, and net P&L in one place.

Charge sources (verified June 2025):
  • https://zerodha.com/charges/#tab-equities
  • https://dhan.co/pricing/

Tax rates: Union Budget 2024 (applicable FY 2024-25 onwards)
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ══════════════════════════════════════════════════════════════════
#  CHARGE CONSTANTS  (FY 2025-26)
# ══════════════════════════════════════════════════════════════════

# Exchange Transaction Charges (% of turnover on each leg)
EXCHANGE_TXN = {
    "NSE": 0.0000307,    # 0.00307%
    "BSE": 0.0000375,    # 0.00375%
}

# SEBI Turnover Fee: ₹10 per crore = 0.0001% of turnover
SEBI_PER_CRORE = 10.0   # i.e. 10 / 1e7 fraction

# GST: 18% on (brokerage + exchange txn + SEBI charges)
GST_RATE = 0.18

# Stamp Duty (on buy-side value only)
STAMP_DUTY = {
    "delivery": 0.00015,   # 0.015%
    "intraday": 0.00003,   # 0.003%
}

# STT / CTT
STT = {
    "delivery": {"buy": 0.001, "sell": 0.001},   # 0.1% each
    "intraday": {"buy": 0.0,   "sell": 0.00025}, # 0.025% sell only
}

# Platform-specific brokerage rules
BROKERAGE_RULES = {
    "zerodha": {
        "delivery": {"mode": "zero"},
        "intraday": {"mode": "pct_or_flat", "pct": 0.0003, "flat": 20},
    },
    "dhan": {
        "delivery": {"mode": "zero"},
        "intraday": {"mode": "pct_or_flat", "pct": 0.0003, "flat": 20},
    },
}

# DP (Depository Participant) charges — charged per scrip on delivery sell
DP_CHARGES = {
    "zerodha": 15.34,   # ₹3.5 CDSL + ₹9.5 broker + ₹2.34 GST
    "dhan":    14.75,    # ₹12.50 + GST
}

# ── Tax rates (post Union Budget 2024) ──────────────────────────
STCG_RATE       = 0.20       # 20% for listed equity (holding < 12 months)
LTCG_RATE       = 0.125      # 12.5% for listed equity (holding >= 12 months)
LTCG_EXEMPTION  = 125_000    # ₹1.25 lakh per FY
CESS_RATE       = 0.04       # 4% Health & Education Cess on tax


# ══════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════

@dataclass
class TradeCharges:
    brokerage_buy: float = 0.0
    brokerage_sell: float = 0.0
    stt_buy: float = 0.0
    stt_sell: float = 0.0
    exchange_buy: float = 0.0
    exchange_sell: float = 0.0
    sebi: float = 0.0
    stamp_duty: float = 0.0
    gst: float = 0.0
    dp_charges: float = 0.0

    @property
    def total_brokerage(self) -> float:
        return round(self.brokerage_buy + self.brokerage_sell, 2)

    @property
    def total_stt(self) -> float:
        return round(self.stt_buy + self.stt_sell, 2)

    @property
    def total_exchange(self) -> float:
        return round(self.exchange_buy + self.exchange_sell, 2)

    @property
    def total(self) -> float:
        return round(
            self.total_brokerage + self.total_stt + self.total_exchange +
            self.sebi + self.stamp_duty + self.gst + self.dp_charges, 2
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_brokerage"] = self.total_brokerage
        d["total_stt"]       = self.total_stt
        d["total_exchange"]  = self.total_exchange
        d["total"]           = self.total
        return d


@dataclass
class TradePnL:
    # ── Input ──
    stock: str = ""
    platform: str = ""
    trade_type: str = ""
    exchange: str = ""
    quantity: int = 0
    buy_price: float = 0.0
    sell_price: float = 0.0
    buy_date: str = ""
    sell_date: str = ""
    # ── Computed values ──
    buy_value: float = 0.0
    sell_value: float = 0.0
    turnover: float = 0.0
    gross_pnl: float = 0.0
    charges: TradeCharges = field(default_factory=TradeCharges)
    net_pnl: float = 0.0
    # ── Tax ──
    holding_days: int = 0
    tax_category: str = ""    # STCG / LTCG / Speculative
    taxable_gain: float = 0.0
    tax_rate: float = 0.0
    tax_amount: float = 0.0
    cess: float = 0.0
    total_tax: float = 0.0
    # ── Final ──
    post_tax_pnl: float = 0.0
    return_pct: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["charges"] = self.charges.to_dict()
        return d


# ══════════════════════════════════════════════════════════════════
#  CORE CALCULATION
# ══════════════════════════════════════════════════════════════════

def _brokerage(platform: str, trade_type: str, value: float) -> float:
    rule = BROKERAGE_RULES.get(platform, {}).get(trade_type, {"mode": "zero"})
    mode = rule["mode"]
    if mode == "zero":
        return 0.0
    if mode == "pct_or_flat":
        return round(min(value * rule["pct"], rule["flat"]), 2)
    return 0.0


def calculate_trade(
    stock: str,
    platform: str,
    trade_type: str,
    exchange: str,
    quantity: int,
    buy_price: float,
    sell_price: float,
    buy_date: str,
    sell_date: str,
) -> TradePnL:
    """Calculate complete P&L with all charges and indicative tax."""

    platform   = platform.lower()
    trade_type = trade_type.lower()
    exchange   = exchange.upper()

    buy_value  = round(buy_price * quantity, 2)
    sell_value = round(sell_price * quantity, 2)
    turnover   = round(buy_value + sell_value, 2)
    gross_pnl  = round(sell_value - buy_value, 2)

    # ── Charges ──────────────────────────────────────────────────
    ch = TradeCharges()

    # Brokerage
    ch.brokerage_buy  = _brokerage(platform, trade_type, buy_value)
    ch.brokerage_sell = _brokerage(platform, trade_type, sell_value)

    # STT
    stt = STT[trade_type]
    ch.stt_buy  = round(buy_value * stt["buy"], 2)
    ch.stt_sell = round(sell_value * stt["sell"], 2)

    # Exchange Transaction Charges
    exch_rate = EXCHANGE_TXN.get(exchange, EXCHANGE_TXN["NSE"])
    ch.exchange_buy  = round(buy_value * exch_rate, 2)
    ch.exchange_sell = round(sell_value * exch_rate, 2)

    # SEBI
    ch.sebi = round(turnover * SEBI_PER_CRORE / 1e7, 2)

    # Stamp Duty (buy side only)
    ch.stamp_duty = round(buy_value * STAMP_DUTY[trade_type], 2)

    # DP Charges (delivery sell only — flat per scrip)
    if trade_type == "delivery":
        ch.dp_charges = DP_CHARGES.get(platform, 15.34)
    else:
        ch.dp_charges = 0.0

    # GST: 18% on (brokerage + exchange txn + SEBI)
    gst_base = ch.total_brokerage + ch.total_exchange + ch.sebi
    ch.gst = round(gst_base * GST_RATE, 2)

    net_pnl = round(gross_pnl - ch.total, 2)

    # ── Tax classification ───────────────────────────────────────
    buy_dt  = datetime.strptime(buy_date, "%Y-%m-%d").date()
    sell_dt = datetime.strptime(sell_date, "%Y-%m-%d").date()
    holding_days = max(0, (sell_dt - buy_dt).days)

    if trade_type == "intraday":
        holding_days = 0
        tax_category = "Speculative"
        # Speculative income taxed at slab rate; we show 30% as indicative
        tax_rate = 0.30
    elif holding_days >= 365:
        tax_category = "LTCG"
        tax_rate = LTCG_RATE
    else:
        tax_category = "STCG"
        tax_rate = STCG_RATE

    # Tax on profit only (per-trade; FY-level LTCG exemption applied in summary)
    taxable_gain = max(0.0, net_pnl)
    tax_amount   = round(taxable_gain * tax_rate, 2)
    cess         = round(tax_amount * CESS_RATE, 2)
    total_tax    = round(tax_amount + cess, 2)
    post_tax_pnl = round(net_pnl - total_tax, 2)
    return_pct   = round(net_pnl / buy_value * 100, 2) if buy_value > 0 else 0.0

    return TradePnL(
        stock=stock, platform=platform, trade_type=trade_type,
        exchange=exchange, quantity=quantity,
        buy_price=buy_price, sell_price=sell_price,
        buy_date=buy_date, sell_date=sell_date,
        buy_value=buy_value, sell_value=sell_value, turnover=turnover,
        gross_pnl=gross_pnl, charges=ch, net_pnl=net_pnl,
        holding_days=holding_days, tax_category=tax_category,
        taxable_gain=taxable_gain, tax_rate=tax_rate,
        tax_amount=tax_amount, cess=cess, total_tax=total_tax,
        post_tax_pnl=post_tax_pnl, return_pct=return_pct,
    )


# ══════════════════════════════════════════════════════════════════
#  FY TAX SUMMARY
# ══════════════════════════════════════════════════════════════════

def _fy_label(dt_str: str) -> str:
    """Return FY label for a sell date, e.g. 'FY 2025-26'."""
    d = datetime.strptime(dt_str, "%Y-%m-%d").date()
    if d.month >= 4:
        return f"FY {d.year}-{str(d.year+1)[-2:]}"
    return f"FY {d.year-1}-{str(d.year)[-2:]}"


def calculate_fy_summary(trades_with_pnl: list[dict]) -> list[dict]:
    """
    Aggregate trades by FY and compute net tax with LTCG exemption.
    Each item in trades_with_pnl must have keys: sell_date, pnl (TradePnL.to_dict()).
    Returns list of FY summaries sorted by FY.
    """
    from collections import defaultdict
    buckets = defaultdict(lambda: {
        "stcg_profit": 0, "stcg_loss": 0,
        "ltcg_profit": 0, "ltcg_loss": 0,
        "speculative_profit": 0, "speculative_loss": 0,
        "total_charges": 0, "trade_count": 0,
    })

    for t in trades_with_pnl:
        pnl = t["pnl"]
        fy = _fy_label(t["sell_date"])
        b = buckets[fy]
        b["trade_count"] += 1
        b["total_charges"] += pnl["charges"]["total"]
        net = pnl["net_pnl"]
        cat = pnl["tax_category"]

        if cat == "STCG":
            if net >= 0:
                b["stcg_profit"] += net
            else:
                b["stcg_loss"] += abs(net)
        elif cat == "LTCG":
            if net >= 0:
                b["ltcg_profit"] += net
            else:
                b["ltcg_loss"] += abs(net)
        else:  # Speculative
            if net >= 0:
                b["speculative_profit"] += net
            else:
                b["speculative_loss"] += abs(net)

    result = []
    for fy in sorted(buckets):
        b = buckets[fy]

        # ── Loss set-off rules ──
        # ST loss offsets STCG first, then LTCG
        st_net = b["stcg_profit"] - b["stcg_loss"]
        lt_net = b["ltcg_profit"] - b["ltcg_loss"]
        spec_net = b["speculative_profit"] - b["speculative_loss"]

        # If STCG is net loss, set off against LTCG
        excess_st_loss = 0
        if st_net < 0:
            excess_st_loss = abs(st_net)
            st_net = 0
            lt_net = lt_net - excess_st_loss
            if lt_net < 0:
                lt_net = 0  # carry-forward not modelled here

        # LTCG exemption ₹1.25L
        ltcg_taxable = max(0, lt_net - LTCG_EXEMPTION)
        stcg_taxable = max(0, st_net)
        spec_taxable = max(0, spec_net)

        stcg_tax = round(stcg_taxable * STCG_RATE, 2)
        ltcg_tax = round(ltcg_taxable * LTCG_RATE, 2)
        spec_tax = round(spec_taxable * 0.30, 2)  # indicative slab

        total_tax = stcg_tax + ltcg_tax + spec_tax
        cess = round(total_tax * CESS_RATE, 2)
        total_with_cess = round(total_tax + cess, 2)

        result.append({
            "fy": fy,
            "trade_count":       b["trade_count"],
            "total_charges":     round(b["total_charges"], 2),
            "stcg_profit":       round(b["stcg_profit"], 2),
            "stcg_loss":         round(b["stcg_loss"], 2),
            "stcg_net":          round(max(0, st_net), 2),
            "stcg_tax":          stcg_tax,
            "ltcg_profit":       round(b["ltcg_profit"], 2),
            "ltcg_loss":         round(b["ltcg_loss"], 2),
            "ltcg_exemption":    min(LTCG_EXEMPTION, max(0, lt_net)),
            "ltcg_taxable":      ltcg_taxable,
            "ltcg_tax":          ltcg_tax,
            "speculative_profit": round(b["speculative_profit"], 2),
            "speculative_loss":  round(b["speculative_loss"], 2),
            "speculative_tax":   spec_tax,
            "cess":              cess,
            "total_tax":         total_with_cess,
        })

    return result
