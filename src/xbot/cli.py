"""
X Reply Bot CLI

Usage:
    python -m src.xbot [OPTIONS] POST_URL_OR_ID

Examples:
    python -m src.xbot https://x.com/user/status/1234567890
    python -m src.xbot 1234567890 --num-replies 3
    python -m src.xbot https://x.com/... --post-best
    python -m src.xbot https://x.com/... --context "I'm a crypto founder, keep it on-brand"
"""

from __future__ import annotations

import os
import sys

import click
from dotenv import load_dotenv

from .reply_analyzer import analyze_top_replies
from .reply_generator import ReplyGenerator
from .x_client import XClient

load_dotenv()

# ── colour helpers ────────────────────────────────────────────────────────────
def _c(text: str, code: str) -> str:
    """Wrap text in ANSI colour if stdout is a TTY."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"

def bold(t: str) -> str:   return _c(t, "1")
def green(t: str) -> str:  return _c(t, "32")
def yellow(t: str) -> str: return _c(t, "33")
def cyan(t: str) -> str:   return _c(t, "36")
def red(t: str) -> str:    return _c(t, "31")
def dim(t: str) -> str:    return _c(t, "2")


def _strength_colour(strength: str) -> str:
    s = strength.lower()
    if s == "high":
        return green(strength)
    if s == "medium":
        return yellow(strength)
    return red(strength)


@click.command(name="xbot")
@click.argument("post_url_or_id")
@click.option(
    "--num-replies", "-n",
    default=5,
    show_default=True,
    help="Number of reply variants to generate.",
)
@click.option(
    "--top-n",
    default=10,
    show_default=True,
    help="How many top existing replies to analyse.",
)
@click.option(
    "--context", "-c",
    default=None,
    help="Optional context about yourself / your brand to guide the tone.",
)
@click.option(
    "--post-best",
    is_flag=True,
    default=False,
    help="Interactively pick and post a reply (requires OAuth credentials).",
)
@click.option(
    "--model",
    default="claude-opus-4-6",
    show_default=True,
    help="Claude model to use for generation.",
)
@click.option(
    "--bearer-token",
    envvar="X_BEARER_TOKEN",
    default=None,
    help="X API Bearer Token (or set X_BEARER_TOKEN env var).",
)
@click.option(
    "--anthropic-key",
    envvar="ANTHROPIC_API_KEY",
    default=None,
    help="Anthropic API key (or set ANTHROPIC_API_KEY env var).",
)
@click.option(
    "--x-api-key",      envvar="X_API_KEY",           default=None, hidden=True)
@click.option(
    "--x-api-secret",   envvar="X_API_SECRET",         default=None, hidden=True)
@click.option(
    "--x-access-token", envvar="X_ACCESS_TOKEN",       default=None, hidden=True)
@click.option(
    "--x-access-secret",envvar="X_ACCESS_TOKEN_SECRET",default=None, hidden=True)
def main(
    post_url_or_id: str,
    num_replies: int,
    top_n: int,
    context: str | None,
    post_best: bool,
    model: str,
    bearer_token: str | None,
    anthropic_key: str | None,
    x_api_key: str | None,
    x_api_secret: str | None,
    x_access_token: str | None,
    x_access_secret: str | None,
):
    """Generate engagement-maximizing replies for an X post."""

    # ── credential checks ─────────────────────────────────────────────────────
    if not bearer_token:
        click.echo(
            red("✗ Missing X Bearer Token. Set X_BEARER_TOKEN or pass --bearer-token.")
        )
        sys.exit(1)
    if not anthropic_key:
        click.echo(
            red("✗ Missing Anthropic API key. Set ANTHROPIC_API_KEY or pass --anthropic-key.")
        )
        sys.exit(1)

    # ── fetch tweet + replies ─────────────────────────────────────────────────
    click.echo(f"\n{bold('X Reply Bot')} — powered by Claude\n")
    click.echo(f"  Fetching tweet: {cyan(post_url_or_id)}")

    x_client = XClient(
        bearer_token=bearer_token,
        api_key=x_api_key,
        api_secret=x_api_secret,
        access_token=x_access_token,
        access_token_secret=x_access_secret,
    )

    try:
        result = x_client.fetch(post_url_or_id, top_n=top_n)
    except Exception as exc:
        click.echo(red(f"✗ Failed to fetch tweet: {exc}"))
        sys.exit(1)

    tweet = result.original
    click.echo(
        f"\n{bold('ORIGINAL TWEET')} by @{cyan(tweet.author_username)}"
        f"  ({tweet.likes} likes · {tweet.retweets} RTs · {tweet.replies} replies)"
    )
    click.echo(f"  \"{tweet.text}\"\n")

    if result.error:
        click.echo(yellow(f"  ⚠  Could not fetch replies: {result.error}"))
        click.echo(yellow("     Generating reply based on tweet content only.\n"))

    replies_fetched = result.top_replies
    if replies_fetched:
        click.echo(
            f"  Analysed {bold(str(len(replies_fetched)))} top-performing replies.\n"
        )
    else:
        click.echo(dim("  No existing replies found — generating from tweet content only.\n"))

    # ── analyse patterns ──────────────────────────────────────────────────────
    pattern = analyze_top_replies(replies_fetched)

    if replies_fetched:
        click.echo(bold("ENGAGEMENT PATTERNS DETECTED:"))
        for line in pattern.describe().splitlines():
            click.echo(f"  {line}")
        click.echo()

    # ── generate replies ──────────────────────────────────────────────────────
    click.echo(f"  Generating {bold(str(num_replies))} reply variants with {bold(model)}…\n")

    generator = ReplyGenerator(api_key=anthropic_key, model=model)
    gen_result = generator.generate(
        tweet=tweet,
        pattern=pattern,
        num_replies=num_replies,
        custom_context=context,
    )

    if gen_result.error:
        click.echo(red(f"✗ Generation error: {gen_result.error}"))
        sys.exit(1)

    # ── display results ───────────────────────────────────────────────────────
    click.echo(bold("GENERATED REPLIES:"))
    click.echo("─" * 60)

    for i, reply in enumerate(gen_result.replies, 1):
        strength_label = _strength_colour(reply.predicted_strength)
        click.echo(
            f"\n{bold(str(i))}. [{strength_label}]  {dim(reply.strategy)}"
        )
        click.echo(f"   {yellow(reply.text)}")
        click.echo(dim(f"   {reply.character_count}/280 characters"))

    click.echo("\n" + "─" * 60)

    # ── interactive posting ───────────────────────────────────────────────────
    if post_best:
        if not all([x_api_key, x_api_secret, x_access_token, x_access_secret]):
            click.echo(
                red("\n✗ Posting requires OAuth credentials:")
                + "\n  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET"
            )
            sys.exit(1)

        click.echo()
        choice = click.prompt(
            "Enter the number of the reply to post (or 0 to cancel)",
            type=click.IntRange(0, len(gen_result.replies)),
        )
        if choice == 0:
            click.echo(dim("Cancelled. No reply was posted."))
            return

        selected = gen_result.replies[choice - 1]
        click.echo(f"\nPosting:\n  {yellow(selected.text)}\n")
        if not click.confirm("Confirm post?"):
            click.echo(dim("Cancelled."))
            return

        try:
            new_id = x_client.post_reply(selected.text, tweet.id)
            click.echo(green(f"✓ Reply posted! https://x.com/i/status/{new_id}"))
        except Exception as exc:
            click.echo(red(f"✗ Failed to post: {exc}"))
            sys.exit(1)


if __name__ == "__main__":
    main()
