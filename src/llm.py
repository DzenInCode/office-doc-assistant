"""Claude API wrapper with prompt caching for repeated document questions."""
from __future__ import annotations

import logging
import os

from anthropic import Anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "4096"))

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers user questions about a document "
    "they have uploaded. Base your answers strictly on the document content. "
    "If the answer is not in the document, say so clearly. "
    "Reply in the same language as the user's question."
)


def ask_about_document(
    *,
    document: str,
    question: str,
    client: Anthropic | None = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """Ask Claude a question about a document, using prompt caching.

    The system prompt and document body are placed before the cache breakpoint,
    so repeated questions about the same document within the cache TTL (~5 min)
    are charged at ~10% of the cache-write price.
    """
    client = client or Anthropic()

    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"<document>\n{document}\n</document>",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": question,
                    },
                ],
            }
        ],
    )

    if response.usage.cache_read_input_tokens:
        logger.info(
            "cache hit: read %d tokens",
            response.usage.cache_read_input_tokens,
        )

    return next(
        (b.text for b in response.content if b.type == "text"),
        "",
    ).strip()
