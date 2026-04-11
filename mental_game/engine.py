"""
Mental Game of Trading — Core Engine
All 10 components from Jared Tendler's system.

Pattern recognition, scoring, alerts, emergency protocols,
technical-psychological integration rules.
"""

from __future__ import annotations
from collections import Counter
from datetime import datetime, timedelta


# ════════════════════════════════════════════════════════════════
#  COMPONENT 8 — MENTAL GAME SCORING SYSTEM (1-10)
#  [TENDLER] — Chapter 2: Map Your Pattern, severity scale
#  [TENDLER] — Chapter 9: Real-Time Strategy, threshold concept
# ════════════════════════════════════════════════════════════════

SCORE_BANDS = {
    10: {
        "label": "Peak Performance (A-Game)",
        "desc": "Complete emotional clarity. Fully executing system with zero impulse. Flow state — decisions feel effortless. Confidence stable, discipline locked in.",
        "full_size": True, "reduced_size": True, "no_trade": False,
        "action": "Trade full size. This is your A-game — capture it.",
        "source": "[TENDLER] Ch2 A-game concept; Ch7 stable confidence; Ch9 zone state"
    },
    9: {
        "label": "Excellent (High A/B-Game)",
        "desc": "Occasional minor noise but quickly dismissed. System execution near-perfect. High confidence anchored to process, not results. Emotional threshold far from breach.",
        "full_size": True, "reduced_size": True, "no_trade": False,
        "action": "Trade full size. Minor emotion present but well below threshold.",
        "source": "[TENDLER] Ch2 B-game; Ch9 Yerkes-Dodson — well below performance drop-off"
    },
    8: {
        "label": "Strong (Solid B-Game)",
        "desc": "Mild emotional background noise. Able to recognize and correct quickly. Decision-making quality high. Slight hesitation or eagerness on 1-2 setups.",
        "full_size": True, "reduced_size": True, "no_trade": False,
        "action": "Trade full size. Use Injecting Logic if emotion spikes.",
        "source": "[TENDLER] Ch2 B-game; Ch9 Injecting Logic"
    },
    7: {
        "label": "Good (B-Game Threshold)",
        "desc": "Clearly functioning but emotion is noticeable. May feel residual frustration, anxiety, or eagerness from prior session or life event. Can execute system if deliberate.",
        "full_size": False, "reduced_size": True, "no_trade": False,
        "action": "Trade at 75% position size. Require 5/5 technical confluence. Active monitoring of emotional signals.",
        "source": "[TENDLER] Ch9 emotional threshold concept; [SYSTEM ARCHITECTURE] position sizing link"
    },
    6: {
        "label": "Below Average (C-Game Risk)",
        "desc": "Emotion is actively interfering. Catch yourself thinking about results, not process. Mild fear, impatience, or frustration affecting analysis. Decision quality degraded.",
        "full_size": False, "reduced_size": True, "no_trade": False,
        "action": "Trade at 50% position size only. Maximum 2 trades. Require 5/5 confluence. Mandatory 10-min reset between trades.",
        "source": "[TENDLER] Ch2 C-game; Ch8 discipline failure signals; [SYSTEM ARCHITECTURE] trade limits"
    },
    5: {
        "label": "Compromised (C-Game Active)",
        "desc": "Significant emotional interference. Racing thoughts, revenge impulse, FOMO, or paralysis. Accumulated emotion from prior losses or life stress clearly affecting judgment.",
        "full_size": False, "reduced_size": True, "no_trade": False,
        "action": "Trade at 50% size, maximum 1 trade. Paper trade as alternative. Run full real-time strategy before any entry. 15-min cooldown between decisions.",
        "source": "[TENDLER] Ch2 accumulated emotion; Ch9 real-time 4-step strategy"
    },
    4: {
        "label": "Poor (Below C-Game)",
        "desc": "Emotional state is dominant. Unable to analyze objectively. Strong urge to act impulsively — revenge trade, panic exit, oversize. Physical signs: tension, rapid breathing, restlessness.",
        "full_size": False, "reduced_size": False, "no_trade": True,
        "action": "DO NOT TRADE. Paper trade only if compelled. Run Injecting Logic protocol. Walk away for minimum 30 minutes. Write Mental Hand History.",
        "source": "[TENDLER] Ch9 Yerkes-Dodson — past threshold; Ch9 quitting as strategy"
    },
    3: {
        "label": "Dangerous (Tilt/Fear/Greed Active)",
        "desc": "Full tilt, panic, or greed spiral. Cannot think clearly. Prior losses replaying. Compulsive checking, physical agitation. Prefrontal cortex is shut down by emotional system.",
        "full_size": False, "reduced_size": False, "no_trade": True,
        "action": "STOP ALL TRADING. Close screens. Deep diaphragmatic breathing for 5 minutes. Write down everything you are feeling. Do NOT return today unless score recovers to 7+.",
        "source": "[TENDLER] Ch6 tilt; Ch9 malfunctioning mind — brain hierarchy shutdown"
    },
    2: {
        "label": "Critical (Emotional Breakdown)",
        "desc": "Desperation state. Multiple blown rules. Significant losses from emotional trading. Feeling of 'I need to make it back NOW.' Revenge and desperation combined.",
        "full_size": False, "reduced_size": False, "no_trade": True,
        "action": "STOP TRADING IMMEDIATELY. Do NOT return today. Activate Emergency Protocol B or F. Complete Mental Hand History in evening. Consider taking tomorrow off.",
        "source": "[TENDLER] Ch7 Desperation section; Ch6 revenge trading"
    },
    1: {
        "label": "Crisis (Burnout/Total Breakdown)",
        "desc": "Complete loss of control. Blown account rules, massive drawdown from emotional trades. Cannot think, cannot stop. Questioning whether to continue trading.",
        "full_size": False, "reduced_size": False, "no_trade": True,
        "action": "STOP ALL TRADING FOR MINIMUM 48 HOURS. Contact mentor or accountability partner. Complete full written review. Do not trade until score is 7+ for 3 consecutive sessions.",
        "source": "[TENDLER] Ch10 Burnout; Ch7 Desperation 10-step plan"
    },
}


def get_score_band(score: int) -> dict:
    """Return the band definition for a given mental score."""
    score = max(1, min(10, score))
    return SCORE_BANDS[score]


# ════════════════════════════════════════════════════════════════
#  COMPONENT 12 — TECHNICAL-PSYCHOLOGICAL INTEGRATION
#  [SYSTEM ARCHITECTURE] — Connection 1-4 from requirements
# ════════════════════════════════════════════════════════════════

def get_position_size_pct(mental_score: int) -> int:
    """Return max position size % based on mental game score.
    [TENDLER] Ch9 emotional threshold + Yerkes-Dodson law
    [SYSTEM ARCHITECTURE] Connection 2 — Position Size Link"""
    if mental_score >= 9:
        return 100
    elif mental_score == 8:
        return 100
    elif mental_score == 7:
        return 75
    elif mental_score in (5, 6):
        return 50
    else:
        return 0  # No trading


def get_min_confluence(mental_score: int) -> int:
    """Return minimum technical confluence score required.
    [TENDLER] Ch9 — higher emotion = need more evidence
    [SYSTEM ARCHITECTURE] Connection 1 — Confluence Scoring Adjustment"""
    if mental_score >= 8:
        return 4  # Normal: 4/5
    elif mental_score == 7:
        return 5  # Elevated: 5/5 only
    elif mental_score in (5, 6):
        return 5  # 5/5 only, with reduced size
    else:
        return 99  # Effectively no trading


def get_max_trades(mental_score: int) -> int:
    """Max trades allowed today based on mental score.
    [INFERRED FROM TENDLER] Ch8 discipline — limit exposure when compromised
    [SYSTEM ARCHITECTURE] — daily trade limit"""
    if mental_score >= 8:
        return 99  # Unlimited
    elif mental_score == 7:
        return 5
    elif mental_score == 6:
        return 2
    elif mental_score == 5:
        return 1
    else:
        return 0


# ════════════════════════════════════════════════════════════════
#  COMPONENT 7 — PATTERN RECOGNITION & ALERT SYSTEM
#  [TENDLER] Ch2: Map Your Pattern + Ch3: Find the Root
#  [TENDLER] Ch9: recognizing patterns before threshold breach
# ════════════════════════════════════════════════════════════════

PATTERN_DEFINITIONS = {
    "REVENGE_TRADE": {
        "name": "Revenge Trading",
        "early_warnings": [
            "Increasing frustration after consecutive losses",
            "Urge to 'make it back' immediately",
            "Checking P&L compulsively between trades",
            "Sizing up after a loss without system signal",
        ],
        "confirmation": [
            "Entered trade within 5 minutes of a loss without system signal",
            "Position size increased after loss",
            "Broke entry rules — entered at suboptimal level",
            "Trade was not on watchlist or pre-session plan",
        ],
        "immediate_action": "STOP. Close screens for 10 minutes. Deep diaphragmatic breathing. Write: 'The last loss is done. This moment is independent. My system works over time, not per trade.' [TENDLER] Ch6 Tilt — Revenge Trading; Ch9 Injecting Logic",
        "recovery": "Complete Mental Hand History on the revenge impulse. Identify whether anger, injustice, or need-to-be-right triggered it. Map the escalation path. Resume only when score is 7+. [TENDLER] Ch3 Mental Hand History",
        "prevention": "Track consecutive losses. After 2 consecutive losses, MANDATORY 15-minute break. Write correction statement before returning. [TENDLER] Ch6 Joe's 100-box system",
        "source": "[TENDLER] Ch6 Revenge Trading"
    },
    "OVERCONFIDENCE": {
        "name": "Overconfidence Pattern",
        "early_warnings": [
            "Feeling 'certain' about a trade outcome before entry",
            "Skipping steps in pre-trade checklist",
            "Increasing position size after winning streak",
            "Dismissing warning signals from the system",
        ],
        "confirmation": [
            "3+ consecutive wins led to larger position size",
            "Entered trade with less than normal confluence",
            "Felt invincible — 'I can't lose right now'",
            "Ignored stop loss or moved it further away",
        ],
        "immediate_action": "PAUSE. Run pre-trade checklist from scratch. Ask: 'Would I take this trade at normal size if last 3 trades were losses?' If answer is no, skip the trade. [TENDLER] Ch7 Illusion of Control #1",
        "recovery": "Review the A-to-C game analysis. What does your C-game look like when overconfident? List specific mistakes. Reduce size to 75% for next 3 trades. [TENDLER] Ch7 Brendan's story",
        "prevention": "After 3 consecutive wins: reduce position size to 75%. No increases above normal size. Track 'confidence score' separately from mental score. [TENDLER] Ch7 stable confidence concept",
        "source": "[TENDLER] Ch7 Overconfidence, Illusions of Control"
    },
    "FEAR_PARALYSIS": {
        "name": "Fear Pattern",
        "early_warnings": [
            "Hesitating on valid setups that meet all criteria",
            "Opening 1-minute chart and watching every tick",
            "Reducing position size below plan without reason",
            "Negative future thinking: 'What if this goes wrong?'",
        ],
        "confirmation": [
            "Missed 2+ valid setups due to hesitation",
            "Exited winning trade early out of fear of giving back profit",
            "Moved stop loss too tight, guaranteeing stop-out",
            "Second-guessed system after it gave clear signal",
        ],
        "immediate_action": "TAKE THE TRADE at reduced size (50%) as exposure therapy. Ask: 'Is this setup valid per my system? YES or NO.' If YES, execute. The fear is about the outcome, which you cannot control. [TENDLER] Ch5 Fear of Pulling Trigger",
        "recovery": "Track all missed setups and their outcomes. Calculate the cost of NOT acting. Often fear costs more than loss. Write: 'I trust my system over my fear.' [TENDLER] Ch5 Fear of Losing Money",
        "prevention": "Run 'What's the worst that happens?' exercise. Answer: 'I lose my stop loss amount, which is predefined and acceptable.' Separate fear from genuine caution (caution = system-based reason; fear = emotional). [TENDLER] Ch5 Uncertainty as root of fear",
        "source": "[TENDLER] Ch5 Fear"
    },
    "DISCIPLINE_BREAKDOWN": {
        "name": "Discipline Breakdown",
        "early_warnings": [
            "Skipping pre-session mental checklist",
            "Not logging trades properly",
            "Feeling 'I know what I'm doing, don't need the process'",
            "Trading while distracted (phone, news, chat)",
        ],
        "confirmation": [
            "Broke 2+ rules in a single session",
            "No pre-trade checklist completed for last trade",
            "Deviated from system on entry, size, stop, or target",
            "Traded a setup not in the trading plan",
        ],
        "immediate_action": "STOP after current trade completes. Re-read your trading rules physically. Complete the pre-trade checklist before ANY next trade. Ask: 'Am I trading my system or my emotions right now?' [TENDLER] Ch8 Nature of discipline",
        "recovery": "Map the discipline failure. Was it willpower (low energy) or mental strength (weak connection to the rule)? If willpower: take a break, reduce trading duration. If mental strength: review WHY the rule exists. [TENDLER] Ch8 Mental Strength vs Willpower",
        "prevention": "Start each session with full warmup routine. Use Pomodoro technique for focus (25-min blocks). Track discipline score daily. [TENDLER] Ch8 Brian's Pomodoro story",
        "source": "[TENDLER] Ch8 Discipline"
    },
    "FOMO": {
        "name": "FOMO (Fear of Missing Out)",
        "early_warnings": [
            "Watching a stock run without you and feeling urge to chase",
            "Entering at extended price because 'it might go higher'",
            "Seeing others profit and feeling left behind",
            "Abandoning normal entry criteria to catch a move",
        ],
        "confirmation": [
            "Entered trade above optimal entry with no system signal",
            "Chased price into resistance / supply zone",
            "Entered without checking pre-trade technical and psychological gates",
            "Regret about 'missing' the move drove the decision",
        ],
        "immediate_action": "CLOSE THE CHART. There will be another setup. Write: 'Missing a trade costs me nothing. Taking a bad trade costs me capital AND confidence.' The market gives opportunities daily — you only need a few. [TENDLER] Ch5 FOMO section",
        "recovery": "Count how many valid setups your system gave you this week. If > 5, FOMO is irrational. Track missed trades and their eventual outcomes — many reverse. [TENDLER] Ch5 Nick's story — FOMO correction",
        "prevention": "Pre-plan 3-5 setups with specific entry prices each morning. If price runs past entry, LET IT GO. Add 'FOMO check' to pre-trade gate: 'Am I chasing or was this planned?' [INFERRED FROM TENDLER] Ch5 FOMO + Ch8 impatience",
        "source": "[TENDLER] Ch5 FOMO"
    },
    "EARLY_EXIT": {
        "name": "Early Exit (Fear of Giving Back Profit)",
        "early_warnings": [
            "Checking unrealized P&L every few seconds",
            "Mental calculation of profit before target reached",
            "Urge to 'lock in' profit at first pullback",
            "Shifting focus from system target to current P&L",
        ],
        "confirmation": [
            "Exited trade before target with no system exit signal",
            "Moved target closer without technical reason",
            "Took profit at breakeven + small gain out of fear",
        ],
        "immediate_action": "STOP watching P&L. Set alert at target and step away. Write: 'My system defined the target based on analysis, not my comfort level. I trust the analysis.' [TENDLER] Ch5 Fear of Losing Money, Ch4 Greed",
        "recovery": "Track all early exits vs what happened at original target. Calculate money left on the table. This data kills the fear over time. [INFERRED FROM TENDLER] Mental Hand History applied to exits",
        "prevention": "Set hard targets in broker platform. Do not watch P&L mid-trade. Use time-based check-ins (every 15 minutes) instead of price-watching. [TENDLER] Ch8 being overly results-oriented",
        "source": "[TENDLER] Ch5 Fear + Ch4 Greed"
    },
    "OVERSIZE_AFTER_WIN": {
        "name": "Oversizing After Win",
        "early_warnings": [
            "Feeling 'I'm on a roll' after wins",
            "Calculating how much faster money grows at bigger size",
            "Justifying larger size as 'playing with house money'",
        ],
        "confirmation": [
            "Position size increased 25%+ after winning streak",
            "Size decision based on recent P&L, not system rules",
            "Risk per trade exceeds maximum defined in plan",
        ],
        "immediate_action": "REVERT to standard position size. The next trade is independent of the last. Write: 'Variance goes both ways. My edge plays out over 100+ trades, not 3.' [TENDLER] Ch4 Greed; Ch7 Illusion of Control #4",
        "recovery": "Review Vince risk metrics. Compare current size to optimal f. If oversized, the math says you will eventually blow up. [INFERRED FROM TENDLER] — merged with Vince system",
        "prevention": "Position size is MECHANICAL — determined by system, not by recent results. Lock size rules in your plan. [TENDLER] Ch4 Alex's story — greed from confidence",
        "source": "[TENDLER] Ch4 Greed, Ch7 Overconfidence"
    },
    "BOREDOM_OVERTRADE": {
        "name": "Boredom Overtrading",
        "early_warnings": [
            "Feeling restless during quiet market",
            "Scrolling through charts looking for 'something'",
            "Forcing setups that don't fully meet criteria",
            "Taking trades to feel engaged rather than profitable",
        ],
        "confirmation": [
            "Entered 3+ trades in a session with no A-quality setups",
            "Traded outside normal window from boredom",
            "Post-trade review: 'I knew it wasn't great but took it anyway'",
        ],
        "immediate_action": "STOP trading. Stand up. Walk for 5 minutes. Boredom is a signal the market has nothing for you right now. Return only for A-quality setups. [TENDLER] Ch8 Boredom — Michael's energy trader story",
        "recovery": "Track trades taken 'because bored' vs planned trades. Compare win rates. Boredom trades always have lower expectancy. [TENDLER] Ch8 boredom → overtrading link",
        "prevention": "Use 'backup quarterback' mentality — stay ready, don't force action. Rate each session: How many trades were system-driven vs emotion-driven? [TENDLER] Ch8 Boredom section",
        "source": "[TENDLER] Ch8 Boredom"
    },
}


def detect_patterns(trades: list[dict]) -> list[dict]:
    """Analyze recent trades and return active pattern alerts.
    [TENDLER] Ch2: Map Your Pattern — recognition is the first step
    [SYSTEM ARCHITECTURE] Connection 3 — Pattern Tag Analysis"""
    alerts = []
    if not trades:
        return alerts

    # Count pattern tags
    tags = [t.get("pattern_tag", "") for t in trades if t.get("pattern_tag")]
    tag_counts = Counter(tags)

    # Alert if any pattern appears 3+ times in the dataset
    for tag, count in tag_counts.items():
        if count >= 3 and tag in PATTERN_DEFINITIONS:
            defn = PATTERN_DEFINITIONS[tag]
            alerts.append({
                "pattern": tag,
                "name": defn["name"],
                "count": count,
                "severity": "HIGH" if count >= 5 else "MODERATE",
                "action": f"Pattern '{defn['name']}' appeared {count} times. Reduce position size by 50% until resolved. {defn['immediate_action']}",
                "source": defn["source"],
            })

    # Detect consecutive losses → revenge risk
    recent = trades[:10]  # Last 10 trades
    consec_losses = 0
    for t in recent:
        if t.get("system_followed") == "NO":
            consec_losses += 1
        else:
            break
    if consec_losses >= 3:
        alerts.append({
            "pattern": "REVENGE_TRADE",
            "name": "Consecutive Rule Breaks",
            "count": consec_losses,
            "severity": "HIGH",
            "action": f"{consec_losses} consecutive rule breaks detected. STOP TRADING. Activate Emergency Protocol F.",
            "source": "[TENDLER] Ch6 Revenge Trading"
        })

    # Detect consecutive wins → overconfidence risk
    consec_wins = 0
    for t in recent:
        sf = t.get("system_followed", "YES")
        emotion = (t.get("pre_emotion") or "").upper()
        if sf == "YES" and emotion in ("OVERCONFIDENT", "GREEDY"):
            consec_wins += 1
        elif sf == "YES":
            consec_wins += 1  # still count wins
        else:
            break
    # Better: track actual consecutive wins based on presence of pattern
    oc_count = sum(1 for t in recent if (t.get("pre_emotion") or "").upper() == "OVERCONFIDENT")
    if oc_count >= 3:
        alerts.append({
            "pattern": "OVERCONFIDENCE",
            "name": "Overconfidence Building",
            "count": oc_count,
            "severity": "MODERATE",
            "action": "Overconfident emotion logged 3+ times recently. Anchor confidence to process, not results. Review A-to-C game analysis.",
            "source": "[TENDLER] Ch7 Overconfidence"
        })

    # Detect FOMO entries
    fomo_count = sum(1 for t in trades if (t.get("pattern_tag") or "").upper() == "FOMO")
    if fomo_count >= 2:
        alerts.append({
            "pattern": "FOMO",
            "name": "FOMO Entries Recurring",
            "count": fomo_count,
            "severity": "HIGH" if fomo_count >= 4 else "MODERATE",
            "action": f"FOMO tagged {fomo_count} times. Pre-plan entries with specific prices. If price runs past, let it go.",
            "source": "[TENDLER] Ch5 FOMO"
        })

    return alerts


# ════════════════════════════════════════════════════════════════
#  COMPONENT 10 — EMERGENCY PROTOCOLS
#  [TENDLER] Ch6 Tilt, Ch7 Desperation, Ch9 Real-Time Strategy,
#            Ch10 Troubleshooting
# ════════════════════════════════════════════════════════════════

EMERGENCY_PROTOCOLS = {
    "A": {
        "name": "After a Large Single Loss",
        "trigger": "Single trade loss exceeds 2% of account OR largest loss in 30 days",
        "steps": [
            "1. CLOSE all other open positions to stop bleeding [TENDLER] Ch9 quitting as strategy",
            "2. Walk away from screen for minimum 15 minutes [TENDLER] Ch9 Disrupt — Newton's first law",
            "3. Deep diaphragmatic breathing — 10 slow breaths [TENDLER] Ch9 Disrupt technique",
            "4. Write down exactly what happened — facts only, no judgment [TENDLER] Ch3 Mental Hand History Step 1",
            "5. Write: 'This loss is within my risk parameters. My system accounts for this. One trade does not define my edge.' [TENDLER] Ch9 Injecting Logic",
            "6. Check mental score. If below 7 → STOP trading for the day [TENDLER] Ch9 emotional threshold",
            "7. If 7+ → reduce position size to 50% for remainder of session [SYSTEM ARCHITECTURE]",
            "8. Complete full Mental Hand History in evening cooldown [TENDLER] Ch3 Mental Hand History",
        ],
        "source": "[TENDLER] Ch6 Tilt; Ch9 Real-Time Strategy"
    },
    "B": {
        "name": "After 3+ Consecutive Losses",
        "trigger": "3 or more consecutive losing trades in a single session",
        "steps": [
            "1. STOP trading immediately — do not take another trade [TENDLER] Ch9 quitting as strategy",
            "2. Leave the trading desk for 30 minutes minimum [TENDLER] Ch9 Disrupt]",
            "3. Write down each loss: Was it a system trade or emotional trade? [TENDLER] Ch3 Mental Hand History]",
            "4. If ANY were emotional trades → activate Protocol F [TENDLER] Ch6 revenge trading",
            "5. If ALL were valid system trades → write: 'Variance is normal. 3 losses in a row happens X% of the time with my win rate. My system is intact.' [TENDLER] Ch7 Illusion of Control #4 — ignoring variance",
            "6. Check mental score. If below 6 → done for the day [TENDLER] Ch9 emotional threshold",
            "7. If 6+ → may resume after 30-min break at 50% size, maximum 1 more trade [SYSTEM ARCHITECTURE]",
            "8. Complete full post-session review in evening [TENDLER] Ch9 Cooldown routine",
        ],
        "source": "[TENDLER] Ch6 Tilt; Ch7 Illusion of Control #4; Ch9 Cooldown"
    },
    "C": {
        "name": "After a Large Single Win",
        "trigger": "Single trade profit exceeds 3x normal average OR best trade in 30 days",
        "steps": [
            "1. CELEBRATE briefly — acknowledge the win [TENDLER] Ch7 handling feedback correctly",
            "2. IMMEDIATELY remind yourself: 'This win does not change my system or my edge. The next trade is independent.' [TENDLER] Ch7 Illusion of Control #3 — predicting outcomes",
            "3. Do NOT increase position size on next trade [TENDLER] Ch4 Greed; Ch7 Overconfidence]",
            "4. Run pre-trade checklist with extra rigor on next trade [TENDLER] Ch7 stable confidence]",
            "5. Check for overconfidence signals: Am I feeling 'certain' about next trade? [TENDLER] Ch7 common signs]",
            "6. Write: 'I will not conflate this outcome with my skill level. My skill is in repeating the process.' [TENDLER] Ch7 Illusion of Learning #1 — premature mastery]",
            "7. Maintain standard position size for remainder of session [SYSTEM ARCHITECTURE]",
        ],
        "source": "[TENDLER] Ch4 Greed; Ch7 Overconfidence, Illusions of Control"
    },
    "D": {
        "name": "After 3+ Consecutive Wins",
        "trigger": "3 or more consecutive winning trades",
        "steps": [
            "1. Acknowledge the streak — but do NOT let it inflate confidence [TENDLER] Ch7 Overconfidence]",
            "2. Ask: 'Am I feeling certain about the next trade?' If YES → that's overconfidence [TENDLER] Ch7 Illusion of Control #3]",
            "3. Reduce position size to 75% for next 3 trades as preventive measure [SYSTEM ARCHITECTURE]",
            "4. Re-run full pre-trade checklist with zero shortcuts [TENDLER] Ch7 common signs of overconfidence — cutting corners]",
            "5. Write: 'Winning streaks end. My edge is statistical, not magical. The next trade has the same probability as always.' [TENDLER] Ch7 Illusion of Control #4]",
            "6. Track whether quality of setups is maintained or declining [TENDLER] Ch7 Brendan's story]",
            "7. If setup quality is declining → STOP and resume next session [INFERRED FROM TENDLER]",
        ],
        "source": "[TENDLER] Ch4 Greed; Ch7 Overconfidence; Brendan's story"
    },
    "E": {
        "name": "When About to Break a Rule",
        "trigger": "You recognize the impulse to deviate from your system mid-trade or pre-trade",
        "steps": [
            "1. RECOGNIZE the impulse — this is Step 1 of the Real-Time Strategy [TENDLER] Ch9 Recognize]",
            "2. DISRUPT: Take 3 deep breaths. Stand up. Physically move. [TENDLER] Ch9 Disrupt — Newton's first law",
            "3. INJECT LOGIC: Say your trained correction statement out loud. Examples:",
            "   — Fear: 'My stop loss is my maximum risk. I've already accepted that loss.' [TENDLER] Ch5]",
            "   — Greed: 'My target is based on analysis, not hope. Stick to the plan.' [TENDLER] Ch4]",
            "   — Tilt: 'This trade is independent. The last loss is gone. Execute the system.' [TENDLER] Ch6]",
            "   — FOMO: 'Missing a trade costs nothing. A bad trade costs capital.' [TENDLER] Ch5]",
            "   — Overconfidence: 'I'm not certain. I'm following probability.' [TENDLER] Ch7]",
            "4. STRATEGIC REMINDER: List 3 common mistakes you make when breaking this rule [TENDLER] Ch9]",
            "5. If impulse remains → DO NOT TAKE THE TRADE. Walk away. [TENDLER] Ch9 quitting]",
            "6. Log the near-miss in your journal — this is progress, not failure [TENDLER] Ch9 evaluate progress]",
        ],
        "source": "[TENDLER] Ch9 Real-Time Strategy 4-Step Process"
    },
    "F": {
        "name": "After Breaking a Rule",
        "trigger": "You already broke a trading rule — the damage is done",
        "steps": [
            "1. ACCEPT it happened. Do not beat yourself up — self-criticism is counterproductive [TENDLER] Ch7 Desperation — correct self-criticism]",
            "2. If in a trade: manage it by the book from this point forward. DO NOT compound the error. [TENDLER] Ch6 Revenge Trading]",
            "3. After the trade closes: STOP trading for minimum 15 minutes [TENDLER] Ch9 Disrupt]",
            "4. Write a Mental Hand History immediately:",
            "   Step 1: Describe exactly what happened [TENDLER] Ch3]",
            "   Step 2: Why did I break the rule? What emotion drove it? [TENDLER] Ch3]",
            "   Step 3: What is flawed about that thinking? [TENDLER] Ch3]",
            "   Step 4: What is the correct thinking? [TENDLER] Ch3]",
            "   Step 5: Why is the correction right? [TENDLER] Ch3]",
            "5. Identify which of the 5 Tendler problems caused the break: Fear / Greed / Anger / Confidence / Discipline [TENDLER] Ch4-8]",
            "6. Check mental score. If below 6 → DONE for the day [TENDLER] Ch9 emotional threshold]",
            "7. If 6+ → may resume at 50% size after completing Steps 3-5 [SYSTEM ARCHITECTURE]",
            "8. Tag this trade with the appropriate pattern tag in your journal [TENDLER] Ch2 Map Your Pattern]",
        ],
        "source": "[TENDLER] Ch3 Mental Hand History; Ch6 Tilt; Ch9 Real-Time Strategy"
    },
}


# ════════════════════════════════════════════════════════════════
#  COMPONENT 4 — IN-TRADE PSYCHOLOGICAL RULES
#  [TENDLER] Ch4-8 specific situations + Ch9 Real-Time Strategy
# ════════════════════════════════════════════════════════════════

IN_TRADE_RULES = [
    {
        "situation": "Trade moves against you immediately after entry",
        "rule": "DO NOTHING for the first 5 minutes. Your stop loss is your plan. Do NOT move stop further away. Write: 'My analysis was pre-trade. The market owes me nothing. My stop is where it should be.'",
        "source": "[TENDLER] Ch5 Fear of Losing Money; Ch6 Tilt from losing"
    },
    {
        "situation": "You feel urge to move stop loss further away",
        "rule": "NEVER move stop loss further from entry unless your SYSTEM (not emotions) generates a new signal. Ask: 'Is there a technical reason to move this stop, or am I afraid of being stopped out?' If emotional → do NOT move. If technical → document the reason BEFORE moving.",
        "source": "[TENDLER] Ch5 Fear; Ch8 Discipline — knowing the rule but not following"
    },
    {
        "situation": "Trade at target but you want to hold for more",
        "rule": "TAKE PROFIT at target. If your system has a trailing stop mechanism, use THAT — not your greed. Ask: 'Did I plan to trail this, or am I hoping for more?' If hoping → exit at target. Write: 'My target was set by analysis. Taking the planned profit IS the system.'",
        "source": "[TENDLER] Ch4 Greed — running winners past targets; Ch7 Hope and Wishing"
    },
    {
        "situation": "You feel urge to add to a losing position",
        "rule": "DO NOT ADD. This is averaging down driven by ego, not analysis. Ask: 'Would I enter a NEW position here with the same size?' If NO → do NOT add. If YES → only add if your SYSTEM gives a fresh entry signal at this level with proper stop.",
        "source": "[TENDLER] Ch6 Revenge Trading variant; Ch4 Greed"
    },
    {
        "situation": "You feel urge to exit a winning trade too early",
        "rule": "Check: Is your system giving an exit signal? NO → stay in trade. Hide P&L. Set alert at target and walk away. The urge to exit early is fear of giving back profit — it's FEAR, not prudence. Write: 'I will let my winners run as my system designed.'",
        "source": "[TENDLER] Ch5 Fear of Losing Money (profit version); Ch4 intersection with fear"
    },
    {
        "situation": "You break a rule mid-trade",
        "rule": "IMMEDIATELY acknowledge it. Manage the trade safely to completion (do not compound errors). After trade closes, activate Emergency Protocol F. DO NOT take another trade until Protocol F is fully completed.",
        "source": "[TENDLER] Ch6 Tilt; Ch9 Real-Time Strategy"
    },
    {
        "situation": "Between-trade reset needed",
        "rule": "Stand up. Take 5 deep breaths. Walk for 2 minutes. Return and review: (1) Am I still in system mode or emotional mode? (2) What is my current mental score? (3) Has anything changed since pre-session checklist? If score dropped below 7 → reduce size or stop.",
        "source": "[TENDLER] Ch9 Disrupt + Real-Time Strategy; Ch8 Discipline reset"
    },
]


# ════════════════════════════════════════════════════════════════
#  COMPONENT 2 — PRE-SESSION MENTAL GAME CHECKLIST
#  [TENDLER] Ch9: Build a Productive Routine — Warmup
# ════════════════════════════════════════════════════════════════

PRE_SESSION_CHECKLIST = [
    {"id": "sleep", "question": "Did I sleep 6+ hours last night?", "category": "PHYSICAL", "source": "[TENDLER] Ch10 Burnout — sleep, diet, exercise"},
    {"id": "stress", "question": "Is my stress level manageable today?", "category": "PHYSICAL", "source": "[TENDLER] Ch10 When Life Bleeds Into Trading"},
    {"id": "physical", "question": "Am I physically comfortable (no illness, not hungry, not exhausted)?", "category": "PHYSICAL", "source": "[TENDLER] Ch10 Burnout — physical state"},
    {"id": "financial", "question": "Am I free from financial pressure affecting my trading?", "category": "FINANCIAL", "source": "[TENDLER] Ch7 Desperation — financial pressure driver"},
    {"id": "life", "question": "Are personal life issues contained (not bleeding into trading)?", "category": "EMOTIONAL", "source": "[TENDLER] Ch10 When Life Bleeds Into Trading — bubble technique"},
    {"id": "revenge", "question": "Am I free from desire to 'make back' yesterday's losses?", "category": "EMOTIONAL", "source": "[TENDLER] Ch6 Revenge Trading — accumulated emotion"},
    {"id": "fomo", "question": "Am I approaching today's session without FOMO from missed moves?", "category": "EMOTIONAL", "source": "[TENDLER] Ch5 FOMO"},
    {"id": "plan", "question": "Do I have a written trading plan with specific setups for today?", "category": "DISCIPLINE", "source": "[TENDLER] Ch9 Warmup routine"},
    {"id": "rules", "question": "Have I reviewed my trading rules and Injecting Logic statements?", "category": "DISCIPLINE", "source": "[TENDLER] Ch9 Warmup — review maps, corrections"},
    {"id": "accept", "question": "Can I accept the possibility of multiple losses today and still follow my system?", "category": "MENTAL", "source": "[TENDLER] Ch5 Fear of Losing; Ch7 Illusion of Control #4 — variance"},
]


# ════════════════════════════════════════════════════════════════
#  COMPONENT 3 — PRE-TRADE PSYCHOLOGICAL GATE
#  [TENDLER] Ch9: Real-Time Strategy applied BEFORE entry
# ════════════════════════════════════════════════════════════════

PRE_TRADE_GATE = [
    {"id": "system_entry", "question": "Am I entering from SYSTEM signal, not emotion?", "source": "[TENDLER] Ch8 Discipline — system vs impulse"},
    {"id": "warnings_checked", "question": "Have I checked my early warning signals?", "source": "[TENDLER] Ch9 Recognize step"},
    {"id": "score_check", "question": "Is my current mental score at or above minimum?", "source": "[TENDLER] Ch9 emotional threshold"},
    {"id": "plan_match", "question": "Was this trade on my pre-session plan or watchlist?", "source": "[TENDLER] Ch5 FOMO; Ch8 discipline"},
    {"id": "size_check", "question": "Is my position size within allowed limits for current mental score?", "source": "[SYSTEM ARCHITECTURE] Connection 2"},
]


# ════════════════════════════════════════════════════════════════
#  COMPONENT 9 — LEARNING CURVE TRACKER
#  [TENDLER] Ch1: Inchworm concept; Ch2: competence levels
# ════════════════════════════════════════════════════════════════

COMPETENCE_LEVELS = {
    "UNCONSCIOUS_INCOMPETENCE": {
        "label": "Unconscious Incompetence",
        "short": "UI",
        "desc": "You don't know what you don't know. Problem exists but unrecognized.",
        "source": "[TENDLER] Ch1 Learning Curve model"
    },
    "CONSCIOUS_INCOMPETENCE": {
        "label": "Conscious Incompetence",
        "short": "CI",
        "desc": "You recognize the problem but can't consistently fix it. Mapping and Mental Hand History in progress.",
        "source": "[TENDLER] Ch1 Learning Curve model"
    },
    "CONSCIOUS_COMPETENCE": {
        "label": "Conscious Competence",
        "short": "CC",
        "desc": "You can correct the problem with deliberate effort. Injecting Logic and real-time strategy are working. Progress is visible.",
        "source": "[TENDLER] Ch1 Learning Curve model"
    },
    "UNCONSCIOUS_COMPETENCE": {
        "label": "Unconscious Competence",
        "short": "UC",
        "desc": "The correction is automatic. You no longer generate the problematic emotion. Resolution achieved — this skill is now backend mastery.",
        "source": "[TENDLER] Ch1 Learning Curve model; Ch9 resolution signals"
    },
}


# ════════════════════════════════════════════════════════════════
#  ANALYTICS — Weekly Summary Generator
# ════════════════════════════════════════════════════════════════

def generate_weekly_summary(trades: list[dict]) -> dict:
    """Generate auto-computed weekly summary from trade psychology records.
    [TENDLER] Ch9 Cooldown; [SYSTEM ARCHITECTURE] Component 6"""
    if not trades:
        return {
            "total_trades": 0, "rules_followed": 0, "rules_broken": 0,
            "follow_rate": 0, "common_emotion": "N/A",
            "common_rule_break": "N/A", "common_pattern": "N/A",
            "avg_mental_score": 0, "alerts": [],
        }

    total = len(trades)
    followed = sum(1 for t in trades if t.get("system_followed") == "YES")
    broken = total - followed

    emotions = [t.get("pre_emotion", "") for t in trades if t.get("pre_emotion")]
    emotion_counts = Counter(emotions)
    common_emotion = emotion_counts.most_common(1)[0][0] if emotion_counts else "N/A"

    breaks = [t.get("rule_broken", "") for t in trades if t.get("rule_broken")]
    break_counts = Counter(breaks)
    common_break = break_counts.most_common(1)[0][0] if break_counts else "N/A"

    patterns = [t.get("pattern_tag", "") for t in trades if t.get("pattern_tag")]
    pattern_counts = Counter(patterns)
    common_pattern = pattern_counts.most_common(1)[0][0] if pattern_counts else "N/A"

    scores = [t.get("pre_mental_score", 0) for t in trades if t.get("pre_mental_score")]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    alerts = detect_patterns(trades)

    return {
        "total_trades": total,
        "rules_followed": followed,
        "rules_broken": broken,
        "follow_rate": round(followed / total * 100, 1) if total else 0,
        "common_emotion": common_emotion,
        "common_rule_break": common_break,
        "common_pattern": common_pattern,
        "avg_mental_score": avg_score,
        "emotion_distribution": dict(emotion_counts),
        "pattern_distribution": dict(pattern_counts),
        "alerts": alerts,
    }


# ════════════════════════════════════════════════════════════════
#  DAILY WORKFLOW — Complete Reference
#  [TENDLER] Ch9 Build a Productive Routine
#  [SYSTEM ARCHITECTURE] — full integration
# ════════════════════════════════════════════════════════════════

DAILY_WORKFLOW = {
    "morning": {
        "title": "Morning — Before Market Opens",
        "steps": [
            {"step": 1, "action": "Technical market review (existing system)", "source": "[SYSTEM ARCHITECTURE]"},
            {"step": 2, "action": "Complete Pre-Session Mental Game Checklist (Component 2)", "source": "[TENDLER] Ch9 Warmup routine"},
            {"step": 3, "action": "Record mental score (1-10) in daily session log", "source": "[TENDLER] Ch2 Map Your Pattern"},
            {"step": 4, "action": "Go/No-Go decision: Score 7+ = GO, 5-6 = REDUCED, <5 = NO-GO", "source": "[TENDLER] Ch9 emotional threshold; [SYSTEM ARCHITECTURE]"},
            {"step": 5, "action": "If GO → mark key technical levels and planned setups", "source": "[SYSTEM ARCHITECTURE]"},
            {"step": 6, "action": "If NO-GO → paper trade only, or work on Mental Hand Histories / performance map", "source": "[TENDLER] Ch9 Work the Problem; Ch10 Burnout"},
            {"step": 7, "action": "Review Injecting Logic statements for your top 2 problems", "source": "[TENDLER] Ch9 Warmup — mentally rehearse corrections"},
        ],
    },
    "before_trade": {
        "title": "Before Every Trade",
        "steps": [
            {"step": 1, "action": "Technical pre-trade checklist — 60 seconds (existing system)", "source": "[SYSTEM ARCHITECTURE]"},
            {"step": 2, "action": "Psychological gate (Component 3) — 60 seconds", "source": "[TENDLER] Ch9 Real-Time Strategy"},
            {"step": 3, "action": "Both must pass → only then enter trade", "source": "[SYSTEM ARCHITECTURE]"},
            {"step": 4, "action": "Log pre-trade fields: Emotion + Mental Score", "source": "[TENDLER] Ch2 Map Your Pattern"},
            {"step": 5, "action": "Verify position size matches mental score allowance", "source": "[SYSTEM ARCHITECTURE] Connection 2"},
        ],
    },
    "during_trade": {
        "title": "During Trade",
        "steps": [
            {"step": 1, "action": "In-trade psychological rules active (Component 4)", "source": "[TENDLER] Ch4-8 specific rules"},
            {"step": 2, "action": "Monitor early warning signals from your performance map", "source": "[TENDLER] Ch9 Recognize step"},
            {"step": 3, "action": "If emotion spikes → run 4-step Real-Time Strategy", "source": "[TENDLER] Ch9 Real-Time Strategy"},
            {"step": 4, "action": "Between-trade reset if needed", "source": "[TENDLER] Ch9 Disrupt + Reset"},
        ],
    },
    "after_trade": {
        "title": "After Every Trade",
        "steps": [
            {"step": 1, "action": "Log all technical fields in portfolio tracker", "source": "[SYSTEM ARCHITECTURE]"},
            {"step": 2, "action": "Log psychological fields: System Followed? Rule Broken? Root Cause? In-Trade Emotion? Pattern Tag?", "source": "[TENDLER] Ch2 Map Your Pattern; Ch3 Mental Hand History"},
            {"step": 3, "action": "Write 3-sentence post-trade reflection", "source": "[TENDLER] Ch9 Cooldown routine"},
            {"step": 4, "action": "Check if emergency protocol needed", "source": "[TENDLER] Ch9; [SYSTEM ARCHITECTURE]"},
        ],
    },
    "end_of_session": {
        "title": "End of Trading Session",
        "steps": [
            {"step": 1, "action": "Post-session psychological review — vent emotions in writing", "source": "[TENDLER] Ch9 Cooldown — vent within 30 minutes"},
            {"step": 2, "action": "Check for pattern alerts (Component 7)", "source": "[TENDLER] Ch2 Map Your Pattern"},
            {"step": 3, "action": "Update daily session log with end-of-day mental score", "source": "[TENDLER] Ch9 Cooldown"},
            {"step": 4, "action": "If intense day: write Mini Mental Hand History on worst trade", "source": "[TENDLER] Ch3 Mental Hand History"},
            {"step": 5, "action": "If stable day: review what went well and why", "source": "[TENDLER] Ch9 Evaluate Progress"},
        ],
    },
    "weekly": {
        "title": "Every Friday — Weekly Review",
        "steps": [
            {"step": 1, "action": "Complete Weekly Psychological Report (Component 6)", "source": "[TENDLER] Ch9 Cooldown; [SYSTEM ARCHITECTURE]"},
            {"step": 2, "action": "Identify top recurring pattern from the week", "source": "[TENDLER] Ch2 Map Your Pattern"},
            {"step": 3, "action": "Review pattern alerts and their frequency", "source": "[SYSTEM ARCHITECTURE] Connection 3"},
            {"step": 4, "action": "Set one specific improvement goal for next week", "source": "[TENDLER] Ch9 Evaluate Progress"},
            {"step": 5, "action": "Assess progress: BETTER / SAME / WORSE vs last week", "source": "[TENDLER] Ch9 Evaluate Progress — markers of improvement"},
        ],
    },
    "monthly": {
        "title": "Every Month — Learning Curve Review",
        "steps": [
            {"step": 1, "action": "Update Learning Curve Tracker (Component 9)", "source": "[TENDLER] Ch1 Inchworm concept"},
            {"step": 2, "action": "Assess inchworm direction: Is your floor rising?", "source": "[TENDLER] Ch1 Inchworm — 'suck less'"},
            {"step": 3, "action": "Rate each of the 5 problems on competence scale", "source": "[TENDLER] Ch1 Learning Curve — 4 levels"},
            {"step": 4, "action": "Update performance map if new patterns discovered", "source": "[TENDLER] Ch2 Map Your Pattern"},
            {"step": 5, "action": "Review if any problems have reached resolution", "source": "[TENDLER] Ch9 Evaluate Progress — signals of resolution"},
        ],
    },
}


# ════════════════════════════════════════════════════════════════
#  MASTER QUESTION — The Purpose of the Entire System
# ════════════════════════════════════════════════════════════════

def am_i_trading_system_or_emotions(mental_score: int, gate_passed: bool, system_signal: bool) -> dict:
    """The ONE question: Am I trading my system or my emotions?
    [TENDLER] Core thesis — emotions signal underlying performance flaws
    [SYSTEM ARCHITECTURE] The master integration question"""

    if gate_passed and system_signal and mental_score >= 7:
        return {
            "answer": "SYSTEM",
            "verdict": "You are trading your system.",
            "color": "green",
            "action": "Proceed. Execute the trade as planned.",
        }
    elif system_signal and not gate_passed:
        return {
            "answer": "UNCERTAIN",
            "verdict": "Valid system signal, but psychological gate not passed.",
            "color": "yellow",
            "action": "DO NOT trade until psychological gate passes. The system signal is real — but you are not ready to execute it properly right now.",
        }
    elif gate_passed and not system_signal:
        return {
            "answer": "EMOTIONS",
            "verdict": "No system signal. You are trading your emotions.",
            "color": "red",
            "action": "STOP. There is no system signal. Whatever is driving you to trade is emotional. Identify the emotion and run Injecting Logic.",
        }
    elif mental_score < 5:
        return {
            "answer": "EMOTIONS",
            "verdict": "Mental score too low. You are trading your emotions.",
            "color": "red",
            "action": "DO NOT TRADE. Your mental state is compromised. Follow the protocol for your current score band.",
        }
    else:
        return {
            "answer": "EMOTIONS",
            "verdict": "Neither system signal nor gate passed. This is purely emotional.",
            "color": "red",
            "action": "Walk away. Open your Mental Hand History and work through what's driving this impulse.",
        }
