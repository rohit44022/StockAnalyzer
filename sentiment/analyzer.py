"""
sentiment/analyzer.py — NLP Sentiment Analysis Engine
=====================================================

Uses VADER (Valence Aware Dictionary and sEntiment Reasoner) augmented
with a custom financial lexicon for stock-specific sentiment scoring.

VADER is specifically designed for social media text and handles:
  - Punctuation emphasis (e.g., "AMAZING!!!" vs "amazing")
  - Capitalization (e.g., "GREAT" vs "great")
  - Degree modifiers (e.g., "extremely bullish")
  - Conjunctions (e.g., "good but not great")
  - Negation (e.g., "not bullish")
  - Emoji and emoticons

The financial lexicon adds stock-specific terms that VADER doesn't
know (e.g., "multibagger", "upper circuit", "promoter buying").
"""

from __future__ import annotations
import logging
import re
from collections import Counter
from typing import List, Dict, Any, Tuple

from sentiment.config import (
    FINANCIAL_LEXICON, SOURCES,
    STRONG_BULLISH_THRESHOLD, BULLISH_THRESHOLD,
    BEARISH_THRESHOLD, STRONG_BEARISH_THRESHOLD,
    MIN_POSTS_FOR_CONFIDENCE,
)

logger = logging.getLogger("sentiment.analyzer")

# Type alias
Post = Dict[str, Any]


# ═══════════════════════════════════════════════════════════════
#  VADER INITIALIZATION
# ═══════════════════════════════════════════════════════════════

_analyzer = None


def _get_analyzer():
    """Lazy-initialize VADER with financial lexicon augmentation."""
    global _analyzer
    if _analyzer is not None:
        return _analyzer

    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()
        # Augment with financial terms
        sia.lexicon.update(FINANCIAL_LEXICON)
        _analyzer = sia
        logger.info("VADER initialized with %d financial terms", len(FINANCIAL_LEXICON))
        return _analyzer
    except ImportError:
        logger.error(
            "vaderSentiment not installed — run: pip install vaderSentiment"
        )
        return None


# ═══════════════════════════════════════════════════════════════
#  SINGLE-POST SCORING
# ═══════════════════════════════════════════════════════════════

def score_text(text: str) -> Dict[str, float]:
    """
    Score a single text using VADER + financial lexicon.

    Returns:
        dict with keys: compound, pos, neg, neu
        compound ranges from -1 (most bearish) to +1 (most bullish)
    """
    sia = _get_analyzer()
    if sia is None:
        return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}

    try:
        scores = sia.polarity_scores(text)
        return {
            "compound": scores["compound"],
            "pos": scores["pos"],
            "neg": scores["neg"],
            "neu": scores["neu"],
        }
    except Exception:
        return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}


def classify_sentiment(compound: float) -> str:
    """Classify a compound score into a sentiment label."""
    if compound >= STRONG_BULLISH_THRESHOLD:
        return "STRONG_BULLISH"
    elif compound >= BULLISH_THRESHOLD:
        return "BULLISH"
    elif compound <= STRONG_BEARISH_THRESHOLD:
        return "STRONG_BEARISH"
    elif compound <= BEARISH_THRESHOLD:
        return "BEARISH"
    return "NEUTRAL"


def sentiment_color(label: str) -> str:
    """Return a CSS color for a sentiment label."""
    return {
        "STRONG_BULLISH": "#00c853",
        "BULLISH":        "#66bb6a",
        "NEUTRAL":        "#ffc107",
        "BEARISH":        "#ef5350",
        "STRONG_BEARISH": "#ff1744",
    }.get(label, "#ffc107")


# ═══════════════════════════════════════════════════════════════
#  BATCH SCORING
# ═══════════════════════════════════════════════════════════════

def score_posts(posts: List[Post]) -> List[Post]:
    """
    Score a list of posts. Adds 'sentiment' key to each post dict.

    Each post gets:
        post["sentiment"] = {
            "compound": float,
            "label": str,
            "color": str,
            "pos": float,
            "neg": float,
            "neu": float,
        }
    """
    for post in posts:
        # Combine title + text for scoring (title is usually more informative)
        combined = f"{post.get('title', '')}. {post.get('text', '')}"
        scores = score_text(combined)
        compound = scores["compound"]

        # StockTwits bonus: users explicitly tag posts as Bullish/Bearish.
        # Blend user-tagged sentiment with VADER (60% VADER, 40% user tag)
        # to combine NLP accuracy with human financial judgment.
        meta = post.get("metadata", {})
        user_sent = meta.get("user_sentiment", "")
        if user_sent == "Bullish":
            compound = compound * 0.6 + 0.5 * 0.4  # blend with +0.5
        elif user_sent == "Bearish":
            compound = compound * 0.6 + (-0.5) * 0.4  # blend with -0.5
        compound = max(-1.0, min(1.0, compound))

        # Twitter engagement boost: highly-liked tweets carry more weight
        if post.get("platform") == "twitter":
            likes = meta.get("likes", 0)
            rts = meta.get("retweets", 0)
            if likes + rts > 50:
                compound *= 1.15  # 15% amplification for viral tweets
                compound = max(-1.0, min(1.0, compound))

        label = classify_sentiment(compound)

        post["sentiment"] = {
            "compound": round(compound, 4),
            "label": label,
            "color": sentiment_color(label),
            "pos": round(scores["pos"], 3),
            "neg": round(scores["neg"], 3),
            "neu": round(scores["neu"], 3),
        }

    return posts


# ═══════════════════════════════════════════════════════════════
#  AGGREGATE SCORING — weighted by source reliability
# ═══════════════════════════════════════════════════════════════

def compute_aggregate_sentiment(
    scored_posts_by_source: Dict[str, List[Post]],
) -> Dict[str, Any]:
    """
    Compute overall weighted sentiment from all sources.

    Each source has a weight (from config). Within a source,
    all posts are equally weighted. Reddit posts with higher
    upvotes get a slight boost.

    Returns:
        {
            "overall_score": float,     # -1 to +1
            "overall_label": str,
            "overall_color": str,
            "confidence": int,          # 0-100
            "total_posts": int,
            "source_breakdown": [...],
            "distribution": {...},
        }
    """
    source_scores = []
    total_posts = 0
    all_compounds = []
    distribution = {
        "STRONG_BULLISH": 0, "BULLISH": 0, "NEUTRAL": 0,
        "BEARISH": 0, "STRONG_BEARISH": 0,
    }

    source_breakdown = []

    for source_key, posts in scored_posts_by_source.items():
        if not posts:
            continue

        weight = SOURCES.get(source_key, {}).get("weight", 0.2)
        compounds = []

        for p in posts:
            s = p.get("sentiment", {})
            c = s.get("compound", 0)

            # Reddit: weight by engagement (upvotes boost)
            if source_key == "reddit":
                upvotes = p.get("metadata", {}).get("upvotes", 0)
                engagement_mult = 1.0 + min(upvotes / 100, 1.0)  # max 2x
                compounds.append(c * engagement_mult)
            else:
                compounds.append(c)

            label = s.get("label", "NEUTRAL")
            distribution[label] = distribution.get(label, 0) + 1

        if compounds:
            avg_score = sum(compounds) / len(compounds)
            source_label = classify_sentiment(avg_score)
            source_breakdown.append({
                "source": source_key,
                "source_display": SOURCES.get(source_key, {}).get(
                    "description", source_key
                ),
                "count": len(posts),
                "avg_score": round(avg_score, 4),
                "label": source_label,
                "color": sentiment_color(source_label),
                "weight": weight,
            })
            source_scores.append((avg_score, weight))
            total_posts += len(posts)
            all_compounds.extend([c for c in compounds])

    # Weighted average across sources
    if source_scores:
        total_weight = sum(w for _, w in source_scores)
        if total_weight > 0:
            overall = sum(s * w for s, w in source_scores) / total_weight
        else:
            overall = 0.0
    else:
        overall = 0.0

    overall = max(-1.0, min(1.0, overall))  # clamp
    overall_label = classify_sentiment(overall)

    # Confidence: based on number of posts + agreement across sources
    confidence = _compute_confidence(total_posts, source_scores, all_compounds)

    return {
        "overall_score": round(overall, 4),
        "overall_label": overall_label,
        "overall_color": sentiment_color(overall_label),
        "confidence": confidence,
        "total_posts": total_posts,
        "source_breakdown": source_breakdown,
        "distribution": distribution,
    }


def _compute_confidence(
    total_posts: int,
    source_scores: List[Tuple[float, float]],
    all_compounds: List[float],
) -> int:
    """
    Compute confidence (0-100) based on:
      1. Number of posts (more = higher confidence)
      2. Source agreement (all sources agree = higher)
      3. Compound score variance (lower variance = higher)
    """
    if not all_compounds or total_posts == 0:
        return 0

    # Factor 1: Post count (0-40 points)
    count_score = min(total_posts / 30, 1.0) * 40

    # Factor 2: Source agreement (0-35 points)
    if len(source_scores) >= 2:
        signs = [1 if s > 0.05 else (-1 if s < -0.05 else 0)
                 for s, _ in source_scores]
        # All same sign = high agreement
        pos = sum(1 for s in signs if s > 0)
        neg = sum(1 for s in signs if s < 0)
        agreement = max(pos, neg) / len(signs)
        agree_score = agreement * 35
    else:
        agree_score = 15  # Single source = medium

    # Factor 3: Low variance (0-25 points)
    if len(all_compounds) >= 2:
        mean_c = sum(all_compounds) / len(all_compounds)
        variance = sum((c - mean_c) ** 2 for c in all_compounds) / len(all_compounds)
        # Lower variance → higher confidence
        var_score = max(0, (1.0 - min(variance * 4, 1.0))) * 25
    else:
        var_score = 10

    confidence = int(count_score + agree_score + var_score)
    return max(0, min(100, confidence))


# ═══════════════════════════════════════════════════════════════
#  KEYWORD EXTRACTION
# ═══════════════════════════════════════════════════════════════

# Common English stop words to filter out
_STOP_WORDS = frozenset(
    "the a an and or but in on at to for of is it this that was were be been "
    "being have has had do does did will would could should shall may might can "
    "am are not no its with from by as all about which when where who what how "
    "than more most some any each every their our your his her he she they we you "
    "up down out if so just also very too new old over into said says per via "
    "after before between during through under above below near here there then "
    "now only even still just already yet back well much many such own same both "
    "other another these those into been being able across along while upon once "
    "since therefore however although though stock share market trading price "
    "company today yesterday week month year".split()
)


def extract_key_themes(posts: List[Post], top_n: int = 20) -> List[Dict]:
    """
    Extract most frequent meaningful words/phrases from posts.

    Returns list of {"word": str, "count": int, "sentiment_avg": float}
    """
    word_counts = Counter()
    word_sentiments = {}

    for post in posts:
        text = f"{post.get('title', '')} {post.get('text', '')}".lower()
        # Simple word extraction
        words = re.findall(r'\b[a-z]{3,}\b', text)
        compound = post.get("sentiment", {}).get("compound", 0)

        for word in words:
            if word in _STOP_WORDS:
                continue
            word_counts[word] += 1
            if word not in word_sentiments:
                word_sentiments[word] = []
            word_sentiments[word].append(compound)

    # Build result for top words
    result = []
    for word, count in word_counts.most_common(top_n):
        sentiments = word_sentiments.get(word, [0])
        avg_sent = sum(sentiments) / len(sentiments) if sentiments else 0
        result.append({
            "word": word,
            "count": count,
            "sentiment_avg": round(avg_sent, 3),
            "color": sentiment_color(classify_sentiment(avg_sent)),
        })

    return result
