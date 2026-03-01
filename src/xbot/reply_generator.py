"""
Claude-powered reply generator.

Takes the original tweet, top reply patterns, and uses Claude to produce
multiple high-engagement reply candidates ranked by predicted effectiveness.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from .reply_analyzer import ReplyPattern
from .x_client import Tweet

# The system prompt drives Claude's persona and understanding of X engagement dynamics
SYSTEM_PROMPT = """\
You are an expert social media strategist who specializes in crafting viral replies on X (Twitter). \
You deeply understand what makes content go viral: wit, relatability, timing, controversy, humor, \
insight, and emotional resonance. You have studied thousands of high-engagement replies.

Your goal is to craft replies that:
1. Stop the scroll — the first 3 words must be compelling
2. Add value, humor, or a fresh perspective — not generic agreement
3. Encourage engagement — likes, retweets, and further replies
4. Match the tone of the conversation
5. Feel authentic, not like marketing copy
6. Stay under 280 characters unless a longer thread adds clear value

ENGAGEMENT PRINCIPLES you know deeply:
- Humor and wit outperform serious takes by 3-5x on average
- Questions at the end dramatically increase reply rates
- Calling out a counterintuitive angle creates bookmarks
- Short punchy replies (under 15 words) often out-engage long ones
- Emojis used sparingly (1-2 max) can boost likes but overuse kills credibility
- Starting with "This" or "Hot take:" signals an interesting perspective
- Relatability ("We've all been there") drives retweets
- Specific > vague: replace "a lot" with an actual number
- Never start with "I agree" — boring and low engagement
- Avoid corporate speak, buzzwords, and filler phrases
"""


@dataclass
class GeneratedReply:
    text: str
    strategy: str  # Why this reply is expected to perform well
    predicted_strength: str  # "High" / "Medium" / "Low"
    character_count: int = 0

    def __post_init__(self):
        self.character_count = len(self.text)


@dataclass
class GenerationResult:
    replies: list[GeneratedReply] = field(default_factory=list)
    original_tweet: Optional[Tweet] = None
    error: Optional[str] = None


def _format_top_replies(pattern: ReplyPattern) -> str:
    if not pattern.top_replies_summary:
        return "No reply data available — craft based on the tweet content alone."
    lines = []
    for i, r in enumerate(pattern.top_replies_summary, 1):
        lines.append(
            f"{i}. [{r['tone'].upper()}] \"{r['text']}\"\n"
            f"   → {r['likes']} likes, {r['retweets']} RTs "
            f"(engagement score: {r['engagement_score']})"
        )
    return "\n".join(lines)


def _build_user_prompt(
    tweet: Tweet,
    pattern: ReplyPattern,
    num_replies: int,
    custom_context: Optional[str],
) -> str:
    top_replies_block = _format_top_replies(pattern)
    patterns_block = pattern.describe() if pattern.has_enough_data else "Insufficient reply data — use tweet content alone."

    context_block = ""
    if custom_context:
        context_block = f"\nADDITIONAL CONTEXT FROM USER:\n{custom_context}\n"

    return f"""
ORIGINAL TWEET:
Author: @{tweet.author_username} ({tweet.author_name})
Text: "{tweet.text}"
Engagement: {tweet.likes} likes, {tweet.retweets} RTs, {tweet.replies} replies
{context_block}
TOP-PERFORMING REPLIES (sorted by engagement):
{top_replies_block}

ENGAGEMENT PATTERNS FROM TOP REPLIES:
{patterns_block}

---

Generate {num_replies} different reply options for this tweet that would maximize engagement. \
Each reply should use a DIFFERENT strategy/angle so the user has varied choices.

For each reply, return a JSON object with exactly these fields:
- "text": the reply text (max 280 characters)
- "strategy": one sentence explaining why this will get high engagement
- "predicted_strength": one of "High", "Medium", or "Low"

Return ONLY a JSON array of {num_replies} objects. No other text. Example format:
[
  {{
    "text": "Your reply here",
    "strategy": "Leverages humor to make people tag friends",
    "predicted_strength": "High"
  }}
]
"""


class ReplyGenerator:
    def __init__(self, api_key: str, model: str = "claude-opus-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(
        self,
        tweet: Tweet,
        pattern: ReplyPattern,
        num_replies: int = 5,
        custom_context: Optional[str] = None,
    ) -> GenerationResult:
        prompt = _build_user_prompt(tweet, pattern, num_replies, custom_context)

        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()

            # Strip markdown fences if Claude wraps in ```json
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)

            parsed = json.loads(raw)
            replies = [
                GeneratedReply(
                    text=item["text"],
                    strategy=item.get("strategy", ""),
                    predicted_strength=item.get("predicted_strength", "Medium"),
                )
                for item in parsed
            ]
            return GenerationResult(replies=replies, original_tweet=tweet)

        except json.JSONDecodeError as exc:
            return GenerationResult(
                original_tweet=tweet,
                error=f"JSON parse error: {exc}\nRaw response:\n{raw}",
            )
        except Exception as exc:
            return GenerationResult(original_tweet=tweet, error=str(exc))
