"""
education.py — Plain-English definitions for every TA concept.

Source: "Technical Analysis of the Financial Markets" — John J. Murphy
Every indicator, pattern, and concept includes:
  - name        : Short label
  - chapter     : Murphy book chapter reference
  - definition  : What it is (in simple language)
  - how_to_read : How to interpret the values
  - signals     : What buy/sell signals look like
"""

# ═══════════════════════════════════════════════════════════════
#  INDICATOR DEFINITIONS  (Murphy Ch 7, 9, 10)
# ═══════════════════════════════════════════════════════════════

INDICATOR_HELP = {

    "SMA": {
        "name": "Simple Moving Average",
        "chapter": "Ch 9 — Moving Averages",
        "definition": (
            "The Simple Moving Average (SMA) is the average closing price over "
            "a set number of days. For example, a 50-day SMA adds up the last "
            "50 closing prices and divides by 50. It smooths out daily noise "
            "and shows the underlying trend direction."
        ),
        "how_to_read": (
            "• Price ABOVE the SMA = stock is in an uptrend (bullish)\n"
            "• Price BELOW the SMA = stock is in a downtrend (bearish)\n"
            "• SMA sloping UP = trend is rising\n"
            "• SMA sloping DOWN = trend is falling\n"
            "• Shorter SMAs (10, 20) react faster; Longer SMAs (100, 200) show the big picture"
        ),
        "signals": (
            "• BUY when price crosses ABOVE the SMA from below\n"
            "• SELL when price crosses BELOW the SMA from above\n"
            "• Golden Cross: 50-day SMA crosses ABOVE 200-day SMA = strong buy\n"
            "• Death Cross: 50-day SMA crosses BELOW 200-day SMA = strong sell"
        ),
    },

    "EMA": {
        "name": "Exponential Moving Average",
        "chapter": "Ch 9 — Moving Averages",
        "definition": (
            "The Exponential Moving Average gives MORE weight to recent prices "
            "compared to the SMA. This makes it react faster to price changes. "
            "Traders use it for quicker signals. The 12-day and 26-day EMAs are "
            "used in MACD. The 200-day EMA is the 'big trend' line."
        ),
        "how_to_read": (
            "• Same as SMA but responds faster to price changes\n"
            "• Price above EMA = bullish; below = bearish\n"
            "• Multiple EMAs spreading apart = strong trend\n"
            "• Multiple EMAs bunching together = trend losing steam"
        ),
        "signals": (
            "• BUY when faster EMA crosses above slower EMA\n"
            "• SELL when faster EMA crosses below slower EMA\n"
            "• EMA acts as dynamic support in uptrend, resistance in downtrend"
        ),
    },

    "RSI": {
        "name": "Relative Strength Index",
        "chapter": "Ch 10 — Oscillators (Welles Wilder, 1978)",
        "definition": (
            "RSI measures the SPEED and SIZE of price movements on a 0–100 scale. "
            "It compares how much a stock goes up on 'up days' vs how much it "
            "goes down on 'down days' over 14 periods. Think of it as: "
            "'How strong are the buyers compared to the sellers right now?'"
        ),
        "how_to_read": (
            "• RSI above 70 = OVERBOUGHT (price may have risen too fast, pullback likely)\n"
            "• RSI below 30 = OVERSOLD (price may have fallen too much, bounce likely)\n"
            "• RSI at 50 = neutral, neither buyers nor sellers are dominating\n"
            "• In a strong uptrend, RSI stays in the 40–80 range\n"
            "• In a strong downtrend, RSI stays in the 20–60 range"
        ),
        "signals": (
            "• BUY when RSI crosses above 30 from oversold territory\n"
            "• SELL when RSI crosses below 70 from overbought territory\n"
            "• DIVERGENCE: If price makes a new high but RSI doesn't → warning of reversal\n"
            "• FAILURE SWING: RSI crosses above a previous RSI peak = strong buy signal"
        ),
    },

    "MACD": {
        "name": "Moving Average Convergence Divergence",
        "chapter": "Ch 10 — Oscillators (Gerald Appel)",
        "definition": (
            "MACD shows the relationship between two moving averages. "
            "It is calculated as: MACD Line = 12-day EMA minus 26-day EMA. "
            "The Signal Line is a 9-day EMA of the MACD Line. "
            "The Histogram shows the difference between MACD and Signal lines. "
            "Think of it as: 'Is the short-term momentum speeding up or slowing down?'"
        ),
        "how_to_read": (
            "• MACD Line above Signal Line = bullish momentum\n"
            "• MACD Line below Signal Line = bearish momentum\n"
            "• MACD above 0 = price is above longer-term average (uptrend)\n"
            "• MACD below 0 = price is below longer-term average (downtrend)\n"
            "• Histogram getting TALLER = momentum increasing\n"
            "• Histogram getting SHORTER = momentum decreasing"
        ),
        "signals": (
            "• BUY when MACD crosses above Signal Line (bullish crossover)\n"
            "• SELL when MACD crosses below Signal Line (bearish crossover)\n"
            "• STRONG BUY when MACD crosses above zero line\n"
            "• DIVERGENCE: Price makes new high/low but MACD doesn't = reversal warning"
        ),
    },

    "STOCHASTIC": {
        "name": "Stochastic Oscillator",
        "chapter": "Ch 10 — Oscillators (George Lane)",
        "definition": (
            "The Stochastic Oscillator compares a stock's closing price to its "
            "price range (high-low) over 14 days. It answers the question: "
            "'Where did the stock close relative to its recent range?' "
            "The %K line is the fast line, %D is the slow (signal) line. "
            "Values range from 0 to 100."
        ),
        "how_to_read": (
            "• Above 80 = OVERBOUGHT (stock is closing near its highs)\n"
            "• Below 20 = OVERSOLD (stock is closing near its lows)\n"
            "• %K crossing above %D = momentum turning bullish\n"
            "• %K crossing below %D = momentum turning bearish\n"
            "• Works best in sideways (ranging) markets"
        ),
        "signals": (
            "• BUY when %K crosses above %D below the 20 level (oversold)\n"
            "• SELL when %K crosses below %D above the 80 level (overbought)\n"
            "• DIVERGENCE: Price new low but Stochastic higher low = bullish reversal"
        ),
    },

    "WILLIAMS_R": {
        "name": "Williams %R",
        "chapter": "Ch 10 — Oscillators (Larry Williams)",
        "definition": (
            "Williams %R is similar to the Stochastic but shown upside down "
            "(-100 to 0). It measures where today's close is relative to the "
            "highest high over 14 periods. A reading of -20 means the close "
            "is near the high; -80 means the close is near the low."
        ),
        "how_to_read": (
            "• Above -20 = OVERBOUGHT (close near the high of the range)\n"
            "• Below -80 = OVERSOLD (close near the low of the range)\n"
            "• Moving from -80 toward 0 = buying pressure increasing\n"
            "• Moving from -20 toward -100 = selling pressure increasing"
        ),
        "signals": (
            "• BUY when %R crosses above -80 from oversold\n"
            "• SELL when %R crosses below -20 from overbought\n"
            "• Very useful for timing entries in trending markets"
        ),
    },

    "CCI": {
        "name": "Commodity Channel Index",
        "chapter": "Ch 10 — Oscillators (Donald Lambert, 1980)",
        "definition": (
            "CCI measures how far the current price deviates from its "
            "average price. It uses the Typical Price = (High + Low + Close) / 3 "
            "and compares it to the 20-period average. A reading of +100 means "
            "the price is well above average; -100 means well below average."
        ),
        "how_to_read": (
            "• Above +100 = OVERBOUGHT (unusually high vs average)\n"
            "• Below -100 = OVERSOLD (unusually low vs average)\n"
            "• Between -100 and +100 = normal range\n"
            "• CCI consistently above 0 = uptrend; below 0 = downtrend"
        ),
        "signals": (
            "• BUY when CCI crosses above +100 (strong upward move starting)\n"
            "• SELL when CCI crosses below -100 (strong downward move starting)\n"
            "• Return to 0 from +100 region = potential exit for longs"
        ),
    },

    "ADX": {
        "name": "Average Directional Index",
        "chapter": "Ch 10 — Oscillators (Welles Wilder, 1978)",
        "definition": (
            "ADX measures the STRENGTH of a trend, not its direction. "
            "It is derived from two lines: +DI (bullish pressure) and -DI "
            "(bearish pressure). ADX ranges from 0 to 100. A high ADX means "
            "a strong trend (either up or down). A low ADX means no clear trend."
        ),
        "how_to_read": (
            "• ADX above 25 = STRONG trend (trending market — use trend-following tools)\n"
            "• ADX above 40 = VERY STRONG trend\n"
            "• ADX below 20 = WEAK/NO trend (ranging market — use oscillators)\n"
            "• +DI above -DI = buyers are stronger than sellers (uptrend)\n"
            "• -DI above +DI = sellers are stronger than buyers (downtrend)"
        ),
        "signals": (
            "• BUY when +DI crosses above -DI with ADX rising above 25\n"
            "• SELL when -DI crosses above +DI with ADX rising above 25\n"
            "• ADX rising means trend is getting stronger (stay in the trade)\n"
            "• ADX falling means trend is weakening (prepare to exit)"
        ),
    },

    "ATR": {
        "name": "Average True Range",
        "chapter": "Ch 10 (Welles Wilder, 1978)",
        "definition": (
            "ATR measures VOLATILITY — how much a stock typically moves in a day. "
            "True Range is the largest of: (High-Low), (High-Previous Close), "
            "(Low-Previous Close). ATR is the 14-day average of True Range. "
            "Higher ATR = more volatile stock. Lower ATR = calmer stock."
        ),
        "how_to_read": (
            "• Rising ATR = volatility increasing (big moves likely)\n"
            "• Falling ATR = volatility decreasing (calm period)\n"
            "• Use ATR to set stop losses: Stop = Entry ± 2 × ATR\n"
            "• ATR does NOT tell direction — only how much the stock moves"
        ),
        "signals": (
            "• Not a buy/sell indicator itself\n"
            "• Use for STOP LOSS placement: 2× ATR below entry for longs\n"
            "• Use for POSITION SIZING: Risk per share = 2 × ATR\n"
            "• Sudden ATR spike after low ATR = breakout likely"
        ),
    },

    "OBV": {
        "name": "On Balance Volume",
        "chapter": "Ch 7 — Volume (Joe Granville, 1963)",
        "definition": (
            "OBV is a running total that adds volume on UP days and subtracts "
            "volume on DOWN days. The idea is: volume LEADS price. If OBV is "
            "rising, money is flowing INTO the stock (accumulation). If OBV is "
            "falling, money is flowing OUT (distribution). Smart money moves "
            "before price — OBV can reveal this."
        ),
        "how_to_read": (
            "• OBV rising = accumulation (buying pressure, bullish)\n"
            "• OBV falling = distribution (selling pressure, bearish)\n"
            "• OBV making new highs with price = trend confirmed\n"
            "• OBV diverging from price = WARNING of potential reversal"
        ),
        "signals": (
            "• BUY when OBV makes a new high (confirms uptrend)\n"
            "• SELL when OBV makes a new low (confirms downtrend)\n"
            "• DIVERGENCE: Price new high + OBV lower = bearish warning\n"
            "• DIVERGENCE: Price new low + OBV higher = bullish warning"
        ),
    },

    "AD_LINE": {
        "name": "Accumulation/Distribution Line",
        "chapter": "Ch 7 — Volume (Marc Chaikin)",
        "definition": (
            "The A/D Line combines price and volume to show whether a stock is "
            "being accumulated (bought) or distributed (sold). It uses the "
            "close position within the High-Low range, weighted by volume. "
            "If the close is near the high, most of the day's volume is "
            "considered 'accumulation'. Near the low = 'distribution'."
        ),
        "how_to_read": (
            "• Rising A/D Line = accumulation (more buying, bullish)\n"
            "• Falling A/D Line = distribution (more selling, bearish)\n"
            "• Compare with price for divergences\n"
            "• Smoother than OBV, less prone to false signals"
        ),
        "signals": (
            "• A/D confirming price direction = trend is healthy\n"
            "• A/D diverging from price = trend may be about to reverse\n"
            "• A/D rising while price flat = accumulation before breakout"
        ),
    },

    "ICHIMOKU": {
        "name": "Ichimoku Cloud",
        "chapter": "Ichimoku Kinko Hyo (Goichi Hosoda, 1968)",
        "definition": (
            "Ichimoku is a complete trading system in one indicator. It shows "
            "support/resistance, trend direction, momentum, and trade signals "
            "all at once. The 'Cloud' (Kumo) is formed by two lines projected "
            "26 periods ahead. The five lines are: Tenkan-sen (fast), Kijun-sen "
            "(slow), Senkou A & B (cloud), and Chikou (lagging)."
        ),
        "how_to_read": (
            "• Price ABOVE the cloud = BULLISH\n"
            "• Price BELOW the cloud = BEARISH\n"
            "• Price INSIDE the cloud = NEUTRAL / transition\n"
            "• Thick cloud = strong support/resistance\n"
            "• Thin cloud = weak support/resistance\n"
            "• Green cloud (Senkou A > B) = bullish bias\n"
            "• Red cloud (Senkou B > A) = bearish bias"
        ),
        "signals": (
            "• BUY when price breaks above the cloud\n"
            "• SELL when price breaks below the cloud\n"
            "• Tenkan crossing above Kijun = bullish (stronger if above cloud)\n"
            "• Chikou Span above price = additional bullish confirmation"
        ),
    },

    "SUPERTREND": {
        "name": "Supertrend",
        "chapter": "Trend Following Indicator",
        "definition": (
            "Supertrend is a trend-following indicator based on ATR (volatility). "
            "It plots a line that flips between support (below price in uptrend) "
            "and resistance (above price in downtrend). Very popular in the "
            "Indian market for its simplicity. Uses a 10-period ATR with "
            "3× multiplier as the standard setting."
        ),
        "how_to_read": (
            "• Green Supertrend (below price) = UPTREND — stay long\n"
            "• Red Supertrend (above price) = DOWNTREND — stay short or out\n"
            "• Works well in trending markets\n"
            "• Can give false signals in ranging markets"
        ),
        "signals": (
            "• BUY when Supertrend flips from red to green (below price)\n"
            "• SELL when Supertrend flips from green to red (above price)\n"
            "• Use as a trailing stop loss"
        ),
    },

    "KELTNER": {
        "name": "Keltner Channel",
        "chapter": "Ch 9 (Chester Keltner, enhanced by Linda Raschke)",
        "definition": (
            "Keltner Channels are volatility-based bands around an EMA. "
            "Upper band = EMA + 1.5×ATR, Lower band = EMA - 1.5×ATR. "
            "They are similar to Bollinger Bands but use ATR instead of "
            "standard deviation. When Bollinger Bands squeeze INSIDE "
            "Keltner Channels, it signals a volatility squeeze."
        ),
        "how_to_read": (
            "• Price above upper band = strong uptrend or overbought\n"
            "• Price below lower band = strong downtrend or oversold\n"
            "• Price hugging upper band = strong bullish trend\n"
            "• Price mean-reverting to center = ranging market"
        ),
        "signals": (
            "• BUY when price breaks above upper Keltner band with volume\n"
            "• SELL when price breaks below lower Keltner band\n"
            "• BB inside Keltner = squeeze → expect explosive breakout"
        ),
    },

    "AROON": {
        "name": "Aroon Indicator",
        "chapter": "Oscillators (Tushar Chande, 1995)",
        "definition": (
            "Aroon consists of two lines: Aroon Up and Aroon Down (both 0–100). "
            "Aroon Up measures how many periods since the highest high. "
            "Aroon Down measures how many periods since the lowest low. "
            "Think of it as: 'How long ago was the most recent high/low?'"
        ),
        "how_to_read": (
            "• Aroon Up above 70 = stock recently made new highs (bullish)\n"
            "• Aroon Down above 70 = stock recently made new lows (bearish)\n"
            "• Both near 50 = no clear trend\n"
            "• Aroon Up crossing above Aroon Down = new uptrend starting"
        ),
        "signals": (
            "• BUY when Aroon Up crosses above Aroon Down\n"
            "• SELL when Aroon Down crosses above Aroon Up\n"
            "• Aroon Up at 100 = new 25-day high just made (strong)"
        ),
    },

    "VWAP": {
        "name": "Volume Weighted Average Price",
        "chapter": "Volume Analysis",
        "definition": (
            "VWAP is the average price a stock has traded at throughout the "
            "day, weighted by volume. It gives the 'true average' price "
            "that most shares actually traded at. Institutional traders "
            "use VWAP to evaluate their execution quality."
        ),
        "how_to_read": (
            "• Price above VWAP = institutional buyers are likely in control\n"
            "• Price below VWAP = institutional sellers are likely in control\n"
            "• VWAP acts as a magnet — price tends to return to it"
        ),
        "signals": (
            "• BUY when price bounces off VWAP from above (support)\n"
            "• SELL when price gets rejected at VWAP from below (resistance)\n"
            "• Strong close above VWAP = bullish day"
        ),
    },

    "PIVOT_POINTS": {
        "name": "Pivot Points",
        "chapter": "Support/Resistance Analysis",
        "definition": (
            "Pivot Points are calculated from yesterday's High, Low, and Close. "
            "They give you SEVEN key price levels for today: Pivot (center), "
            "three Support levels (S1, S2, S3) and three Resistance levels "
            "(R1, R2, R3). Floor traders have used these for decades."
        ),
        "how_to_read": (
            "• Price above Pivot = bullish bias for the day\n"
            "• Price below Pivot = bearish bias for the day\n"
            "• R1, R2, R3 = overhead resistance levels (potential selling pressure)\n"
            "• S1, S2, S3 = downside support levels (potential buying interest)\n"
            "• Most price action occurs between S1 and R1"
        ),
        "signals": (
            "• BUY at support levels (S1, S2) when uptrend is intact\n"
            "• SELL at resistance levels (R1, R2) when downtrend is intact\n"
            "• Breakout above R1 with volume = strong bullish signal\n"
            "• Breakdown below S1 with volume = strong bearish signal"
        ),
    },

    "ROC": {
        "name": "Rate of Change",
        "chapter": "Ch 10 — Oscillators",
        "definition": (
            "Rate of Change (ROC) measures the percentage change in price "
            "from one period to another. A 14-period ROC answers: "
            "'How much has the price changed compared to 14 days ago?' "
            "It oscillates above and below zero."
        ),
        "how_to_read": (
            "• ROC above 0 = price higher than N periods ago (bullish)\n"
            "• ROC below 0 = price lower than N periods ago (bearish)\n"
            "• ROC rising = momentum increasing\n"
            "• ROC falling = momentum decreasing"
        ),
        "signals": (
            "• BUY when ROC crosses above zero from below\n"
            "• SELL when ROC crosses below zero from above\n"
            "• DIVERGENCE: Price new high + ROC lower high = bearish warning"
        ),
    },

    "FIBONACCI": {
        "name": "Fibonacci Retracements",
        "chapter": "Ch 4 — Basic Concepts of Trend",
        "definition": (
            "Fibonacci retracements are horizontal lines showing where "
            "support and resistance are likely to occur. They are based on "
            "the Fibonacci sequence ratios: 23.6%, 38.2%, 50%, 61.8%, 78.6%. "
            "After a big move, the price often 'retraces' part of the move "
            "before continuing. Murphy says: 'The 38.2%, 50%, and 61.8% levels "
            "are the most commonly watched.'"
        ),
        "how_to_read": (
            "• 23.6% retracement = shallow pullback (strong trend)\n"
            "• 38.2% retracement = normal pullback\n"
            "• 50% retracement = halfway correction (very common)\n"
            "• 61.8% retracement = deep pullback (golden ratio — key level)\n"
            "• 78.6% retracement = very deep — trend may be reversing"
        ),
        "signals": (
            "• BUY at 38.2% or 50% retracement in an uptrend\n"
            "• SELL at 38.2% or 50% retracement in a downtrend\n"
            "• If price holds above 61.8% = trend is still intact\n"
            "• If price breaks below 78.6% = original trend likely over"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════
#  CANDLESTICK PATTERN DEFINITIONS  (Murphy Ch 12)
# ═══════════════════════════════════════════════════════════════

CANDLESTICK_HELP = {

    "DOJI": {
        "name": "Doji",
        "type": "NEUTRAL / REVERSAL WARNING",
        "definition": (
            "A Doji forms when the opening and closing prices are virtually "
            "equal — the candle has almost no body, just upper and lower shadows. "
            "It represents INDECISION: buyers and sellers fought to a draw. "
            "Murphy says: 'By itself, a doji is neutral, but in context it "
            "can signal a potential reversal.'"
        ),
        "significance": (
            "• After an UPTREND: Doji is a warning that buying pressure is exhausted\n"
            "• After a DOWNTREND: Doji is a warning that selling pressure is exhausted\n"
            "• Needs CONFIRMATION from the next candle to act on it"
        ),
    },

    "HAMMER": {
        "name": "Hammer / Hanging Man",
        "type": "REVERSAL",
        "definition": (
            "A small body at the TOP of the range with a long lower shadow "
            "(at least 2× the body size) and little or no upper shadow. "
            "At the bottom of a DOWNTREND, it is called a 'Hammer' (bullish). "
            "At the top of an UPTREND, the same shape is called a 'Hanging Man' "
            "(bearish)."
        ),
        "significance": (
            "• HAMMER (after downtrend): Sellers pushed price down during the day "
            "but buyers fought back and closed near the high → bullish reversal\n"
            "• HANGING MAN (after uptrend): Despite closing near high, the long "
            "lower shadow shows sellers appeared → bearish warning"
        ),
    },

    "ENGULFING": {
        "name": "Bullish / Bearish Engulfing",
        "type": "REVERSAL (STRONG)",
        "definition": (
            "A two-candle pattern where the second candle's body completely "
            "'engulfs' (covers) the first candle's body. A Bullish Engulfing "
            "appears after a downtrend: a small red candle followed by a large "
            "green candle. A Bearish Engulfing appears after an uptrend."
        ),
        "significance": (
            "• BULLISH ENGULFING: The bulls completely overwhelmed the bears "
            "in a single day → strong buy signal\n"
            "• BEARISH ENGULFING: The bears completely overwhelmed the bulls "
            "→ strong sell signal\n"
            "• More reliable at support/resistance levels"
        ),
    },

    "MORNING_STAR": {
        "name": "Morning Star / Evening Star",
        "type": "REVERSAL (STRONG)",
        "definition": (
            "A three-candle pattern. The Morning Star (bullish) appears at the "
            "bottom of a downtrend: first a long red candle, then a small-bodied "
            "candle (the 'star' — shows indecision), then a long green candle "
            "that closes above the midpoint of the first candle. Evening Star "
            "is the opposite at the top of an uptrend."
        ),
        "significance": (
            "• MORNING STAR: Night is ending, dawn is coming → bullish reversal\n"
            "• EVENING STAR: The day is ending, dark is coming → bearish reversal\n"
            "• One of the most reliable candlestick reversal patterns"
        ),
    },

    "THREE_SOLDIERS": {
        "name": "Three White Soldiers / Three Black Crows",
        "type": "CONTINUATION / REVERSAL (STRONG)",
        "definition": (
            "Three consecutive long-bodied candles in the same direction. "
            "'Three White Soldiers' = three long green candles, each opening "
            "within the previous body and closing higher. 'Three Black Crows' "
            "= three long red candles, each opening within the previous body "
            "and closing lower."
        ),
        "significance": (
            "• THREE WHITE SOLDIERS (after downtrend): Powerful bullish reversal\n"
            "• THREE BLACK CROWS (after uptrend): Powerful bearish reversal\n"
            "• Shows sustained, decisive buying/selling pressure over 3 days"
        ),
    },

    "HARAMI": {
        "name": "Harami (bullish/bearish)",
        "type": "REVERSAL (MODERATE)",
        "definition": (
            "A two-candle pattern where the second candle's body is completely "
            "contained within the first candle's body — the opposite of Engulfing. "
            "The word 'harami' means 'pregnant' in Japanese. The small second "
            "candle represents loss of momentum."
        ),
        "significance": (
            "• BULLISH HARAMI: After downtrend, small green candle inside big red candle "
            "→ selling pressure may be exhausting\n"
            "• BEARISH HARAMI: After uptrend, small red candle inside big green candle "
            "→ buying pressure may be fading\n"
            "• Less reliable than Engulfing — wait for confirmation"
        ),
    },

    "PIERCING_DARK_CLOUD": {
        "name": "Piercing Line / Dark Cloud Cover",
        "type": "REVERSAL",
        "definition": (
            "A two-candle pattern. Piercing Line (bullish): after a downtrend, "
            "a red candle followed by a green candle that opens below the "
            "previous low but closes above the midpoint of the red candle. "
            "Dark Cloud Cover (bearish): opposite — a green candle followed "
            "by a red candle that opens above the previous high but closes "
            "below the midpoint."
        ),
        "significance": (
            "• PIERCING LINE: Bulls managed to push price above the midpoint "
            "of yesterday's sell-off → potential bottom\n"
            "• DARK CLOUD COVER: Bears managed to erase more than half "
            "of yesterday's gain → potential top"
        ),
    },

    "SHOOTING_STAR": {
        "name": "Shooting Star / Inverted Hammer",
        "type": "REVERSAL",
        "definition": (
            "A small body at the BOTTOM of the range with a long upper shadow "
            "(at least 2× the body) and little lower shadow — opposite of Hammer. "
            "At the top of an uptrend = 'Shooting Star' (bearish). "
            "At the bottom of a downtrend = 'Inverted Hammer' (bullish)."
        ),
        "significance": (
            "• SHOOTING STAR (after uptrend): Buyers pushed price up but sellers "
            "hammered it back down → bearish reversal\n"
            "• INVERTED HAMMER (after downtrend): Despite rejection there was "
            "buying interest → potential bullish reversal (needs confirmation)"
        ),
    },

    "MARUBOZU": {
        "name": "Marubozu",
        "type": "CONTINUATION (STRONG)",
        "definition": (
            "A candle with a long body and NO shadows (or very tiny shadows). "
            "A green Marubozu opens at the low and closes at the high — "
            "complete buyer domination. A red Marubozu opens at the high "
            "and closes at the low — complete seller domination."
        ),
        "significance": (
            "• GREEN MARUBOZU: Extremely bullish — buyers controlled all day\n"
            "• RED MARUBOZU: Extremely bearish — sellers controlled all day\n"
            "• Shows strong conviction and often marks the start of a move"
        ),
    },

    "SPINNING_TOP": {
        "name": "Spinning Top",
        "type": "NEUTRAL / INDECISION",
        "definition": (
            "A candle with a small body in the middle and long upper and lower "
            "shadows of roughly equal length. Shows that both buyers and sellers "
            "were active but neither side won. Indicates INDECISION."
        ),
        "significance": (
            "• After a big move: spinning top = loss of momentum, possible pause\n"
            "• In a range: spinning top = continuation of indecision\n"
            "• Needs context and confirmation to be meaningful"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════
#  CHART PATTERN DEFINITIONS  (Murphy Ch 5-6)
# ═══════════════════════════════════════════════════════════════

PATTERN_HELP = {

    "HEAD_AND_SHOULDERS": {
        "name": "Head and Shoulders",
        "chapter": "Ch 5 — Major Reversal Patterns",
        "type": "REVERSAL (VERY STRONG)",
        "definition": (
            "The most reliable reversal pattern in technical analysis. It has "
            "three peaks: a middle peak (the 'head') that is HIGHER than two "
            "side peaks (the 'shoulders'). The line connecting the two troughs "
            "is the 'neckline'. The pattern is confirmed when price breaks "
            "below the neckline. Murphy says: 'The head and shoulders pattern "
            "is the most important reversal pattern.'"
        ),
        "significance": (
            "• Occurs at the END of an uptrend → signals reversal to downtrend\n"
            "• PRICE TARGET: Height of head to neckline, projected down from neckline\n"
            "• Volume typically decreases from left shoulder to head to right shoulder\n"
            "• Inverse Head & Shoulders = bullish reversal at bottom of downtrend"
        ),
    },

    "DOUBLE_TOP_BOTTOM": {
        "name": "Double Top / Double Bottom",
        "chapter": "Ch 5 — Major Reversal Patterns",
        "type": "REVERSAL (STRONG)",
        "definition": (
            "Double Top ('M' shape): Price reaches a high, pulls back, rallies "
            "to roughly the same high, then drops. The pattern completes when "
            "price breaks below the middle trough. "
            "Double Bottom ('W' shape): Opposite — price drops to a low, bounces, "
            "drops to roughly the same low, then rallies. Confirmed when price "
            "breaks above the middle peak."
        ),
        "significance": (
            "• Double Top: Resistance tested TWICE and held → bearish reversal\n"
            "• Double Bottom: Support tested TWICE and held → bullish reversal\n"
            "• Price target = height of pattern projected from breakout point\n"
            "• Murphy: 'Volume is usually heavier on the first peak/trough'"
        ),
    },

    "TRIANGLE": {
        "name": "Triangles (Symmetrical, Ascending, Descending)",
        "chapter": "Ch 6 — Continuation Patterns",
        "type": "CONTINUATION (usually)",
        "definition": (
            "Triangles form when the price range narrows between converging "
            "trendlines. Symmetrical: both lines converge equally. "
            "Ascending: flat top + rising bottom (bullish bias). "
            "Descending: flat bottom + falling top (bearish bias). "
            "Murphy: 'Triangles usually resolve in the direction of the prior "
            "trend, but watch for breakouts in either direction.'"
        ),
        "significance": (
            "• Symmetrical Triangle: Pause before continuation (50/50 direction)\n"
            "• Ascending Triangle: Flat resistance + rising support → BULLISH\n"
            "• Descending Triangle: Flat support + falling resistance → BEARISH\n"
            "• Breakout with high volume confirms the pattern"
        ),
    },

    "FLAG_PENNANT": {
        "name": "Flags and Pennants",
        "chapter": "Ch 6 — Continuation Patterns",
        "type": "CONTINUATION (RELIABLE)",
        "definition": (
            "Short-term continuation patterns that mark a brief pause in a "
            "sharp move. A FLAG is a small rectangle that slopes against the "
            "trend. A PENNANT is a small symmetrical triangle. Both appear "
            "after a strong price move (the 'flagpole') and typically resolve "
            "in the direction of the prior move."
        ),
        "significance": (
            "• Usually form in 1-3 weeks\n"
            "• Price target = length of flagpole projected from breakout point\n"
            "• Volume decreases during formation, increases on breakout\n"
            "• Murphy calls them 'the most reliable continuation patterns'"
        ),
    },

    "WEDGE": {
        "name": "Wedges (Rising / Falling)",
        "chapter": "Ch 6 — Continuation Patterns",
        "type": "REVERSAL",
        "definition": (
            "A wedge looks like a triangle but both trendlines slope in the "
            "same direction. Rising Wedge: both lines slope up, but converge "
            "→ BEARISH reversal. Falling Wedge: both lines slope down, "
            "but converge → BULLISH reversal."
        ),
        "significance": (
            "• Rising Wedge = bearish (even though price is going up, "
            "momentum is fading)\n"
            "• Falling Wedge = bullish (even though price is going down, "
            "selling pressure is diminishing)\n"
            "• Takes longer to form than flags or pennants (3-6 weeks)"
        ),
    },

    "SUPPORT_RESISTANCE": {
        "name": "Support and Resistance",
        "chapter": "Ch 4 — Basic Concepts of Trend",
        "type": "FOUNDATIONAL CONCEPT",
        "definition": (
            "SUPPORT is a price level where buying is strong enough to prevent "
            "further decline — think of it as a 'floor'. RESISTANCE is a price "
            "level where selling is strong enough to prevent further rise — "
            "a 'ceiling'. Murphy says: 'Previous support becomes resistance "
            "and previous resistance becomes support (role reversal).'"
        ),
        "significance": (
            "• The more times a level is tested, the stronger it becomes\n"
            "• Higher volume at a level = stronger support/resistance\n"
            "• A decisive break through S/R with volume = significant move\n"
            "• Round numbers (₹100, ₹500, ₹1000) often act as S/R"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════
#  DOW THEORY PRINCIPLES  (Murphy Ch 2)
# ═══════════════════════════════════════════════════════════════

DOW_THEORY = {
    "principle_1": {
        "name": "The Averages Discount Everything",
        "explanation": (
            "All information — earnings, economic data, political events — "
            "is already reflected in the stock price. The market 'knows' "
            "everything. Our job is to read what the price is telling us."
        ),
    },
    "principle_2": {
        "name": "The Market Has Three Trends",
        "explanation": (
            "• PRIMARY TREND: The major direction lasting months to years "
            "(bull or bear market)\n"
            "• SECONDARY TREND: Corrections within the primary trend lasting "
            "weeks to months (typically retraces 33%–66% of the primary move)\n"
            "• MINOR TREND: Daily fluctuations lasting less than three weeks"
        ),
    },
    "principle_3": {
        "name": "Major Trends Have Three Phases",
        "explanation": (
            "• ACCUMULATION: Smart money is buying (prices low, bad news)\n"
            "• PUBLIC PARTICIPATION: Trend followers join (prices rising, "
            "news improving)\n"
            "• DISTRIBUTION: Smart money is selling to latecomers (prices "
            "high, euphoria, great news)"
        ),
    },
    "principle_4": {
        "name": "Volume Must Confirm the Trend",
        "explanation": (
            "In an uptrend, volume should INCREASE when price rises and "
            "DECREASE on pullbacks. In a downtrend, volume should INCREASE "
            "on drops and DECREASE on bounces. If volume contradicts the "
            "trend, the trend may be weakening."
        ),
    },
    "principle_5": {
        "name": "A Trend Is Assumed to Continue Until Definite Signals Prove Otherwise",
        "explanation": (
            "Don't try to predict reversals. Stay with the trend until the "
            "evidence clearly shows it has ended. Murphy says: 'It's a lot "
            "easier to ride a trend than to predict one.'"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════
#  RISK MANAGEMENT CONCEPTS  (Murphy Ch 16)
# ═══════════════════════════════════════════════════════════════

RISK_HELP = {
    "position_sizing": {
        "name": "Position Sizing (How Much to Buy)",
        "definition": (
            "Position sizing determines HOW MANY shares you should buy. "
            "The golden rule: Never risk more than 1-2% of your total capital "
            "on any single trade. This means if you have ₹5,00,000 and risk "
            "2% per trade, your maximum loss per trade should be ₹10,000."
        ),
        "formula": (
            "Position Size (shares) = Risk Amount ÷ Risk Per Share\n"
            "Risk Amount = Capital × Risk % (e.g., 5,00,000 × 0.02 = ₹10,000)\n"
            "Risk Per Share = Entry Price - Stop Loss Price\n"
            "Example: Entry ₹500, Stop ₹480 → Risk/share = ₹20\n"
            "Position = ₹10,000 ÷ ₹20 = 500 shares"
        ),
    },
    "risk_reward": {
        "name": "Risk-Reward Ratio",
        "definition": (
            "Before entering any trade, calculate how much you could LOSE "
            "(risk) vs how much you could GAIN (reward). Murphy says: "
            "'Only take trades where the potential reward is at least 2-3 times "
            "the potential risk.' A 1:3 Risk-Reward means you risk ₹1 to "
            "potentially make ₹3."
        ),
        "formula": (
            "Risk = Entry Price - Stop Loss\n"
            "Reward = Target Price - Entry Price\n"
            "R:R Ratio = Reward ÷ Risk\n"
            "MINIMUM acceptable R:R = 1:2 (risk ₹1 to make ₹2)"
        ),
    },
    "stop_loss": {
        "name": "Stop Loss",
        "definition": (
            "A stop loss is a predefined price at which you EXIT the trade "
            "to limit your loss. Murphy strongly advises: NEVER trade without "
            "a stop loss. Common methods:\n"
            "1. ATR Stop: 2× ATR below entry price\n"
            "2. Percentage Stop: Fixed % below entry (e.g., 5-8%)\n"
            "3. Support Level: Just below the nearest support\n"
            "4. Moving Average: Below 20-day or 50-day SMA"
        ),
    },
    "trailing_stop": {
        "name": "Trailing Stop",
        "definition": (
            "A trailing stop moves WITH the trade as price moves in your "
            "favour, but stays fixed when price moves against you. This "
            "locks in profits while keeping you in the trade if the trend "
            "continues. Parabolic SAR and Supertrend both act as "
            "trailing stops."
        ),
    },
}


def get_indicator_help(indicator_key: str) -> dict | None:
    """Get help text for a specific indicator."""
    return INDICATOR_HELP.get(indicator_key)


def get_candle_help(pattern_key: str) -> dict | None:
    """Get help text for a candlestick pattern."""
    return CANDLESTICK_HELP.get(pattern_key)


def get_pattern_help(pattern_key: str) -> dict | None:
    """Get help text for a chart pattern."""
    return PATTERN_HELP.get(pattern_key)


def get_all_education() -> dict:
    """Return all educational content for the UI."""
    return {
        "indicators":   INDICATOR_HELP,
        "candlesticks":  CANDLESTICK_HELP,
        "patterns":      PATTERN_HELP,
        "dow_theory":    DOW_THEORY,
        "risk_mgmt":     RISK_HELP,
    }
