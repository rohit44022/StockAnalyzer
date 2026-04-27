"""
instruments.py — The macro instrument universe we track.
═════════════════════════════════════════════════════════

Each instrument gets a Yahoo Finance ticker, a category, a "polarity" (does a
RISE indicate risk-on or risk-off?), and a description in plain English.

Polarity convention:
    +1 → a rising price is RISK-ON (growth, optimism)
    -1 → a rising price is RISK-OFF (fear, contraction)
     0 → context-dependent (e.g. DXY: neutral on its own, but a strong USD
          typically pressures EM and commodities)

The categories group instruments for the dashboard:
    fx          — currencies
    commodity   — gold, oil, copper, etc.
    bond        — Treasury yields, VIX
    equity      — global indices
    crypto      — BTC, ETH (modern risk barometer)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    key: str             # internal id
    yf_ticker: str       # yfinance symbol
    name: str            # display name
    category: str        # fx | commodity | bond | equity | crypto
    polarity: int        # +1 risk-on, -1 risk-off, 0 neutral
    unit: str            # display unit ("$", "%", "₹", etc.)
    description: str     # one-line plain English


# ═══════════════════════════════════════════════════════════════
#  Currencies — first-derivative of capital flow
# ═══════════════════════════════════════════════════════════════
FX = [
    Instrument("dxy",     "DX-Y.NYB", "US Dollar Index (DXY)", "fx",  0, "",
               "USD vs basket of 6 majors. Strong DXY → pressure on EM and commodities."),
    Instrument("usdinr",  "INR=X",    "USD/INR",               "fx", -1, "₹",
               "Higher = INR weaker. Rising USD/INR signals FII outflow risk for Indian equities."),
    Instrument("eurinr",  "EURINR=X", "EUR/INR",               "fx",  0, "₹",
               "Euro vs Rupee — relevant for European trade exposure."),
    Instrument("gbpinr",  "GBPINR=X", "GBP/INR",               "fx",  0, "₹",
               "Pound vs Rupee — UK trade & investment exposure."),
    Instrument("jpyinr",  "JPYINR=X", "JPY/INR",               "fx", -1, "₹",
               "Yen vs Rupee. JPY rises in risk-off (carry-trade unwind = global stress)."),
    Instrument("usdcny",  "CNY=X",    "USD/CNY",               "fx",  0, "¥",
               "China currency. Rising USD/CNY = capital outflow / China stress."),
]

# ═══════════════════════════════════════════════════════════════
#  Commodities — growth, inflation, geopolitical risk
# ═══════════════════════════════════════════════════════════════
COMMODITIES = [
    Instrument("gold",    "GC=F", "Gold",            "commodity", -1, "$",
               "The fear gauge. Rises in risk-off, inflation, dollar weakness."),
    Instrument("silver",  "SI=F", "Silver",          "commodity", -1, "$",
               "Industrial + monetary metal. Tracks gold but more volatile."),
    Instrument("brent",   "BZ=F", "Brent Crude",     "commodity",  0, "$",
               "Global oil benchmark. Moderate rise = growth; sharp rise = inflation/geopolitics. India is a major oil importer — pressure on current account."),
    Instrument("wti",     "CL=F", "WTI Crude",       "commodity",  0, "$",
               "US oil benchmark. Tracks Brent with a discount."),
    Instrument("copper",  "HG=F", "Copper (Dr. Copper)", "commodity", +1, "$",
               "The PhD economist of metals. Rising copper → expansion. Falling copper → contraction warning."),
    Instrument("natgas",  "NG=F", "Natural Gas",     "commodity",  0, "$",
               "Energy + heating. Highly seasonal. Spikes signal supply shocks."),
]

# ═══════════════════════════════════════════════════════════════
#  Bonds & Volatility — risk-free rate, recession signal, fear
# ═══════════════════════════════════════════════════════════════
BONDS = [
    Instrument("us10y",   "^TNX", "US 10Y Yield",         "bond",  0, "%",
               "The risk-free rate. Above 4.5% = capital pulled to US bonds, bearish for EM equities."),
    Instrument("us3m",    "^IRX", "US 3M T-Bill",         "bond",  0, "%",
               "Short-end of US curve. 10Y-3M inversion is the NY Fed's preferred recession signal."),
    Instrument("us30y",   "^TYX", "US 30Y Yield",         "bond",  0, "%",
               "Long bond. Term premium signals long-run inflation expectations."),
    Instrument("vix",     "^VIX", "US VIX (S&P fear)",    "bond", -1, "",
               "Implied volatility on S&P 500. >25 = fear, <15 = complacency."),
    Instrument("indiavix","^INDIAVIX", "India VIX",       "bond", -1, "",
               "Implied volatility on Nifty 50 — the actual fear gauge for Indian markets. >20 = elevated, >25 = fear, <13 = complacency."),
]

# ═══════════════════════════════════════════════════════════════
#  Equity indices — sentiment proxy across regions
# ═══════════════════════════════════════════════════════════════
EQUITIES = [
    Instrument("sp500",   "^GSPC",  "S&P 500",     "equity", +1, "",
               "US large-cap. The global risk benchmark."),
    Instrument("nasdaq",  "^IXIC",  "Nasdaq",      "equity", +1, "",
               "US tech / high-growth. Most sensitive to US 10Y yield changes."),
    Instrument("dow",     "^DJI",   "Dow Jones",   "equity", +1, "",
               "US blue-chip / industrial. Less rate-sensitive than Nasdaq."),
    Instrument("ftse",    "^FTSE",  "FTSE 100",    "equity", +1, "£",
               "UK large-cap. Heavy in commodities and banks."),
    Instrument("dax",     "^GDAXI", "DAX (Germany)","equity", +1, "€",
               "German blue-chip. Eurozone industrial bellwether."),
    Instrument("nikkei",  "^N225",  "Nikkei 225",  "equity", +1, "¥",
               "Japan large-cap. Inversely correlated with JPY strength."),
    Instrument("hangseng","^HSI",   "Hang Seng",   "equity", +1, "HK$",
               "Hong Kong. Window into China sentiment."),
    Instrument("nifty",   "^NSEI",  "Nifty 50",    "equity", +1, "₹",
               "India's primary benchmark. The home market."),
    Instrument("sensex",  "^BSESN", "Sensex",      "equity", +1, "₹",
               "India's 30-stock benchmark. Tracks Nifty closely."),
]

# ═══════════════════════════════════════════════════════════════
#  Indian Sector Indices — actionable for an Indian investor
# ═══════════════════════════════════════════════════════════════
SECTORS = [
    Instrument("banknifty",  "^NSEBANK",   "Bank Nifty",     "sector", +1, "₹",
               "12 largest Indian banks. Highly rate-sensitive — sells off on rising US/India yields, rallies on rate cuts."),
    Instrument("niftyit",    "^CNXIT",     "Nifty IT",       "sector", +1, "₹",
               "Indian IT services. INVERSELY correlated to rupee — weak rupee BENEFITS IT (export earnings worth more in INR)."),
    Instrument("niftyauto",  "^CNXAUTO",   "Nifty Auto",     "sector", +1, "₹",
               "Auto OEMs + component makers. Sensitive to commodity prices (steel, aluminium) and consumer demand."),
    Instrument("niftypharma","^CNXPHARMA", "Nifty Pharma",   "sector", +1, "₹",
               "Pharma & healthcare. Defensive sector — outperforms in risk-off, has USD-export angle."),
    Instrument("niftymetal", "^CNXMETAL",  "Nifty Metal",    "sector", +1, "₹",
               "Steel, aluminium, copper, zinc. Highly cyclical — outperforms in risk-on/inflation regimes, suffers in recession."),
    Instrument("niftyfmcg",  "^CNXFMCG",   "Nifty FMCG",     "sector", +1, "₹",
               "Consumer staples. Defensive — outperforms in risk-off and high-inflation. Domestic demand driven."),
    Instrument("niftyenergy","^CNXENERGY", "Nifty Energy",   "sector", +1, "₹",
               "Reliance, ONGC, Power Grid, Coal India. Mixed — upstream benefits from oil up, downstream (OMCs) suffers."),
    Instrument("niftyrealty","^CNXREALTY", "Nifty Realty",   "sector", +1, "₹",
               "Real estate. Most rate-sensitive sector — moves inversely to interest rates."),
]

# ═══════════════════════════════════════════════════════════════
#  Crypto — modern risk barometer
# ═══════════════════════════════════════════════════════════════
CRYPTO = [
    Instrument("btc",     "BTC-USD", "Bitcoin",   "crypto", +1, "$",
               "Highly correlated with Nasdaq in risk-on regimes. Decoupling from equities can signal regime change."),
    Instrument("eth",     "ETH-USD", "Ethereum",  "crypto", +1, "$",
               "Crypto risk-curve — moves more than BTC, both directions."),
]

ALL_INSTRUMENTS = FX + COMMODITIES + BONDS + EQUITIES + SECTORS + CRYPTO

# Convenience lookups
BY_KEY = {i.key: i for i in ALL_INSTRUMENTS}
BY_TICKER = {i.yf_ticker: i for i in ALL_INSTRUMENTS}


def by_category(cat: str) -> list:
    return [i for i in ALL_INSTRUMENTS if i.category == cat]
