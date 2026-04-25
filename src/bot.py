"""Telegram bot that answers questions about uploaded documents using Claude."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from anthropic import Anthropic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.llm import ask_about_document
from src.parser import SUPPORTED_EXTENSIONS, parse

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "20"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_REPLY_CHARS = 4000  # Telegram message limit is 4096; leave headroom


@dataclass
class StoredDocument:
    filename: str
    content: str


# In-memory store: {chat_id: StoredDocument}. For production, swap for Redis.
_documents: dict[int, StoredDocument] = {}
_anthropic = Anthropic()


WELCOME = (
    "Hi! Send me an Excel, CSV, or PDF file, then ask me anything about it.\n\n"
    f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}\n"
    f"Max file size: {MAX_FILE_SIZE_MB} MB.\n\n"
    "Commands:\n"
    "  /start, /help — show this message\n"
    "  /clear — forget the current document"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _documents.pop(update.effective_chat.id, None)
    await update.message.reply_text("Document forgotten. Send a new one.")


async def handle_document(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message
    doc = msg.document
    if doc is None:
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE_BYTES:
        await msg.reply_text(
            f"File too large ({doc.file_size / 1024 / 1024:.1f} MB). "
            f"Max is {MAX_FILE_SIZE_MB} MB."
        )
        return

    filename = doc.file_name or "unknown"
    file = await doc.get_file()
    data = bytes(await file.download_as_bytearray())

    try:
        content = parse(filename, data)
    except ValueError as exc:
        await msg.reply_text(str(exc))
        return
    except Exception:
        logger.exception("parse failed for %s", filename)
        await msg.reply_text("Could not read this file. Is it valid?")
        return

    _documents[msg.chat_id] = StoredDocument(filename=filename, content=content)
    await msg.reply_text(
        f"Got '{filename}' ({len(content):,} characters of text). "
        "Ask me anything about it."
    )


async def handle_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message
    question = (msg.text or "").strip()
    if not question:
        return

    stored = _documents.get(msg.chat_id)
    if stored is None:
        await msg.reply_text(
            "Send me a document first (Excel, CSV, or PDF), then ask."
        )
        return

    await msg.chat.send_action(ChatAction.TYPING)
    try:
        answer = ask_about_document(
            document=stored.content,
            question=question,
            client=_anthropic,
        )
    except Exception:
        logger.exception("LLM call failed")
        await msg.reply_text("Something went wrong asking Claude. Try again.")
        return

    if not answer:
        await msg.reply_text("(empty response)")
        return

    for chunk in _split(answer, MAX_REPLY_CHARS):
        await msg.reply_text(chunk)


def _split(text: str, limit: int) -> list[str]:
    """Split a long string into Telegram-sized chunks at line boundaries."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and buf:
            parts.append("".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line)
    if buf:
        parts.append("".join(buf))
    return parts


def build_app() -> Application:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = build_app()
    logger.info("bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
