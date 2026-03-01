"""
Analyzes top-performing replies to extract engagement patterns.

These patterns are fed to the AI generator so it can replicate what works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .x_client import Tweet


EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff"
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\u2600-\u26FF\u2700-\u27BF]+",
    flags=re.UNICODE,
)

QUESTION_RE = re.compile(r"\?")
EXCLAIM_RE = re.compile(r"!")
HASHTAG_RE = re.compile(r"#\w+")
MENTION_RE = re.compile(r"@\w+")
URL_RE = re.compile(r"https?://\S+")


def _detect_tone(text: str) -> str:
    """Classify reply tone into broad categories."""
    lower = text.lower()
    if any(w in lower for w in ("lmao", "lol", "haha", "💀", "😂", "🤣", "bruh", "dead")):
        return "humor/meme"
    if QUESTION_RE.search(text):
        return "question"
    if any(w in lower for w in ("agree", "exactly", "this", "facts", "true", "correct", "yes")):
        return "agreement"
    if any(w in lower for w in ("wrong", "no ", "nope", "actually", "disagree", "false", "not")):
        return "pushback"
    if any(w in lower for w in ("source", "study", "research", "data", "evidence", "prove")):
        return "factual/educational"
    if any(w in lower for w in ("congrat", "well done", "amazing", "incredible", "love this")):
        return "praise"
    if any(w in lower for w in ("i ", "my ", "me ", "personally", "in my experience")):
        return "personal story"
    return "commentary"


def _word_count(text: str) -> int:
    return len(text.split())


@dataclass
class ReplyPattern:
    avg_word_count: float = 0.0
    median_word_count: float = 0.0
    tone_distribution: dict[str, int] = field(default_factory=dict)
    dominant_tone: str = "commentary"
    emoji_usage_pct: float = 0.0
    question_pct: float = 0.0
    exclamation_pct: float = 0.0
    hashtag_usage_pct: float = 0.0
    url_usage_pct: float = 0.0
    top_replies_summary: list[dict] = field(default_factory=list)
    has_enough_data: bool = False

    def describe(self) -> str:
        """Human-readable summary for prompt injection."""
        lines = [
            f"- Dominant tone: {self.dominant_tone}",
            f"- Average reply length: {self.avg_word_count:.0f} words",
            f"- Emoji usage: {'common' if self.emoji_usage_pct > 0.4 else 'rare'}",
            f"- Questions asked: {'often' if self.question_pct > 0.3 else 'rarely'}",
            f"- Exclamation marks: {'frequent' if self.exclamation_pct > 0.4 else 'infrequent'}",
            f"- Hashtag usage: {'common' if self.hashtag_usage_pct > 0.2 else 'rare'}",
            f"- Tone breakdown: {dict(sorted(self.tone_distribution.items(), key=lambda x: -x[1]))}",
        ]
        return "\n".join(lines)


def analyze_top_replies(replies: list[Tweet]) -> ReplyPattern:
    """Extract engagement patterns from a list of top-performing replies."""
    pattern = ReplyPattern()
    if not replies:
        return pattern

    pattern.has_enough_data = len(replies) >= 3

    word_counts = [_word_count(r.text) for r in replies]
    pattern.avg_word_count = sum(word_counts) / len(word_counts)
    sorted_wc = sorted(word_counts)
    mid = len(sorted_wc) // 2
    pattern.median_word_count = (
        sorted_wc[mid]
        if len(sorted_wc) % 2
        else (sorted_wc[mid - 1] + sorted_wc[mid]) / 2
    )

    with_emoji = sum(1 for r in replies if EMOJI_RE.search(r.text))
    with_question = sum(1 for r in replies if QUESTION_RE.search(r.text))
    with_exclaim = sum(1 for r in replies if EXCLAIM_RE.search(r.text))
    with_hashtag = sum(1 for r in replies if HASHTAG_RE.search(r.text))
    with_url = sum(1 for r in replies if URL_RE.search(r.text))
    n = len(replies)

    pattern.emoji_usage_pct = with_emoji / n
    pattern.question_pct = with_question / n
    pattern.exclamation_pct = with_exclaim / n
    pattern.hashtag_usage_pct = with_hashtag / n
    pattern.url_usage_pct = with_url / n

    tone_dist: dict[str, int] = {}
    for r in replies:
        tone = _detect_tone(r.text)
        tone_dist[tone] = tone_dist.get(tone, 0) + 1
    pattern.tone_distribution = tone_dist
    pattern.dominant_tone = max(tone_dist, key=tone_dist.get)

    # Build summaries of top 5 for the prompt
    for r in replies[:5]:
        pattern.top_replies_summary.append(
            {
                "text": r.text,
                "likes": r.likes,
                "retweets": r.retweets,
                "engagement_score": r.engagement_score,
                "tone": _detect_tone(r.text),
            }
        )

    return pattern
