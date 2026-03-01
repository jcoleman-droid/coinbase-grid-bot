"""
X (Twitter) API v2 client.

Fetches tweet content and top replies sorted by engagement score.
Requires a Bearer Token for read-only access (free tier works for recent tweets).
For posting replies, OAuth 1.0a / OAuth 2.0 user context credentials are also needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import tweepy


@dataclass
class Tweet:
    id: str
    text: str
    author_id: str
    author_username: str
    author_name: str
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    quotes: int = 0
    bookmarks: int = 0
    url: str = ""

    @property
    def engagement_score(self) -> int:
        """Weighted engagement score (higher = better performing)."""
        return (
            self.likes * 2
            + self.retweets * 6
            + self.quotes * 5
            + self.replies * 3
            + self.bookmarks
        )

    @property
    def total_engagement(self) -> int:
        return self.likes + self.retweets + self.replies + self.quotes + self.bookmarks


@dataclass
class FetchResult:
    original: Tweet
    top_replies: list[Tweet] = field(default_factory=list)
    error: Optional[str] = None


def _extract_tweet_id(url_or_id: str) -> str:
    """Accept a tweet URL or raw ID and return the numeric ID string."""
    # Already a numeric ID
    if re.fullmatch(r"\d+", url_or_id.strip()):
        return url_or_id.strip()

    # Match https://x.com/user/status/123... or https://twitter.com/user/status/123...
    match = re.search(r"status/(\d+)", url_or_id)
    if match:
        return match.group(1)

    raise ValueError(
        f"Could not parse tweet ID from: {url_or_id!r}\n"
        "Expected a numeric ID or a URL like https://x.com/user/status/123456789"
    )


class XClient:
    """Thin wrapper around Tweepy v4 Client (Twitter API v2)."""

    TWEET_FIELDS = [
        "public_metrics",
        "author_id",
        "text",
        "conversation_id",
        "created_at",
    ]
    USER_FIELDS = ["username", "name"]
    EXPANSIONS = ["author_id"]

    def __init__(
        self,
        bearer_token: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
    ):
        self._bearer_token = bearer_token
        # Read-only client (app-only auth) — works for fetching tweets
        self._client = tweepy.Client(
            bearer_token=bearer_token,
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            wait_on_rate_limit=True,
        )

    def _build_tweet(self, raw, users_by_id: dict) -> Tweet:
        metrics = raw.public_metrics or {}
        author = users_by_id.get(raw.author_id, {})
        return Tweet(
            id=str(raw.id),
            text=raw.text,
            author_id=str(raw.author_id),
            author_username=author.get("username", ""),
            author_name=author.get("name", ""),
            likes=metrics.get("like_count", 0),
            retweets=metrics.get("retweet_count", 0),
            replies=metrics.get("reply_count", 0),
            quotes=metrics.get("quote_count", 0),
            bookmarks=metrics.get("bookmark_count", 0),
            url=f"https://x.com/i/status/{raw.id}",
        )

    def get_tweet(self, url_or_id: str) -> Tweet:
        tweet_id = _extract_tweet_id(url_or_id)
        resp = self._client.get_tweet(
            tweet_id,
            tweet_fields=self.TWEET_FIELDS,
            user_fields=self.USER_FIELDS,
            expansions=self.EXPANSIONS,
        )
        if not resp.data:
            raise ValueError(f"Tweet {tweet_id} not found or not accessible.")

        users_by_id = {}
        if resp.includes and resp.includes.get("users"):
            for u in resp.includes["users"]:
                users_by_id[u.id] = {"username": u.username, "name": u.name}

        tweet = self._build_tweet(resp.data, users_by_id)
        tweet.url = url_or_id if url_or_id.startswith("http") else tweet.url
        return tweet

    def get_top_replies(
        self, tweet: Tweet, max_results: int = 100, top_n: int = 10
    ) -> list[Tweet]:
        """
        Search for replies in the same conversation, sorted by engagement score.
        Note: search_recent_tweets only covers the past 7 days (free/basic tier).
        """
        query = (
            f"conversation_id:{tweet.id} -is:retweet"
        )
        tweets: list[Tweet] = []
        paginator = tweepy.Paginator(
            self._client.search_recent_tweets,
            query=query,
            tweet_fields=self.TWEET_FIELDS,
            user_fields=self.USER_FIELDS,
            expansions=self.EXPANSIONS,
            max_results=min(max_results, 100),
        )

        for page in paginator:
            if not page.data:
                continue

            users_by_id = {}
            if page.includes and page.includes.get("users"):
                for u in page.includes["users"]:
                    users_by_id[u.id] = {"username": u.username, "name": u.name}

            for raw in page.data:
                # Exclude the original author's own replies (threads)
                if str(raw.author_id) == tweet.author_id:
                    continue
                tweets.append(self._build_tweet(raw, users_by_id))

            if len(tweets) >= max_results:
                break

        tweets.sort(key=lambda t: t.engagement_score, reverse=True)
        return tweets[:top_n]

    def fetch(self, url_or_id: str, top_n: int = 10, max_results: int = 100) -> FetchResult:
        """Full pipeline: fetch tweet + top replies."""
        try:
            original = self.get_tweet(url_or_id)
            top_replies = self.get_top_replies(original, max_results=max_results, top_n=top_n)
            return FetchResult(original=original, top_replies=top_replies)
        except Exception as exc:
            # Return a partial result so the generator can still work with the original
            try:
                original = self.get_tweet(url_or_id)
                return FetchResult(original=original, top_replies=[], error=str(exc))
            except Exception as exc2:
                raise RuntimeError(f"Failed to fetch tweet: {exc2}") from exc2

    def post_reply(self, reply_text: str, in_reply_to_tweet_id: str) -> str:
        """
        Post a reply to a tweet. Requires OAuth user-context credentials
        (api_key, api_secret, access_token, access_token_secret).
        Returns the new tweet's ID.
        """
        resp = self._client.create_tweet(
            text=reply_text,
            in_reply_to_tweet_id=in_reply_to_tweet_id,
        )
        if not resp.data:
            raise RuntimeError("Failed to post reply — no response data.")
        return str(resp.data["id"])
