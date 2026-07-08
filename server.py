"""Telegram MCP server (Telethon + MTProto user account).

Exposes tools over your own Telegram: whoami, recent chats, chat history,
in-chat search, global search across all chats, and sending messages.
Credentials/session live in a local .env created by login.py.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SearchGlobalRequest
from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty

from mcp.server.fastmcp import FastMCP

ENV = Path(__file__).with_name(".env")

# Keep Telethon quiet so it never writes to stdout (which carries the MCP protocol).
logging.getLogger("telethon").setLevel(logging.WARNING)

mcp = FastMCP("telegram")

_client: TelegramClient | None = None


def _get_client() -> TelegramClient:
    """Build the Telethon client from .env, lazily and only once."""
    global _client
    if _client is None:
        load_dotenv(ENV)
        try:
            api_id = int(os.environ["API_ID"])
            api_hash = os.environ["API_HASH"]
            session = os.environ["SESSION_STRING"]
        except KeyError as e:
            raise RuntimeError(
                f"Missing {e} in {ENV}. Run login.py first."
            ) from e
        _client = TelegramClient(StringSession(session), api_id, api_hash)
    return _client


async def _ensure() -> TelegramClient:
    """Connect and confirm the session is authorized before any read."""
    client = _get_client()
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session not authorized. Re-run login.py.")
    return client


def _maybe_int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


async def _resolve(client: TelegramClient, chat: str):
    """Resolve a chat from a username, numeric id, phone, link, or display name."""
    try:
        return await client.get_entity(_maybe_int(chat))
    except Exception:
        pass
    target = str(chat).lower()
    async for dialog in client.iter_dialogs():
        if dialog.name and target in dialog.name.lower():
            return dialog.entity
    raise ValueError(
        f"Could not find a chat matching {chat!r}. "
        "Try a username (@name), a numeric id, or the exact display name."
    )


def _fmt(message) -> dict:
    sender = None
    who = getattr(message, "sender", None)
    if who is not None:
        sender = (
            getattr(who, "username", None)
            or " ".join(
                p for p in [getattr(who, "first_name", None), getattr(who, "last_name", None)] if p
            )
            or getattr(who, "title", None)
        )
    return {
        "id": message.id,
        "date": message.date.isoformat() if message.date else None,
        "from": sender,
        "sender_id": message.sender_id,
        "outgoing": bool(message.out),
        "text": message.message or "",
    }


@mcp.tool()
async def get_me() -> dict:
    """Return the logged-in Telegram account. Use this to confirm whose messages you can see."""
    client = await _ensure()
    me = await client.get_me()
    return {
        "id": me.id,
        "username": me.username,
        "name": " ".join(p for p in [me.first_name, me.last_name] if p),
        "phone": me.phone,
    }


@mcp.tool()
async def list_chats(limit: int = 20) -> list:
    """List your most recent conversations (users, groups, channels), newest first.

    limit: how many chats to return (default 20).
    """
    client = await _ensure()
    out = []
    async for dialog in client.iter_dialogs(limit=limit):
        last = dialog.message
        out.append(
            {
                "id": dialog.id,
                "name": dialog.name,
                "type": "user" if dialog.is_user else "group" if dialog.is_group else "channel",
                "unread": dialog.unread_count,
                "last_message": (last.message[:200] if last and last.message else None),
                "last_date": last.date.isoformat() if last and last.date else None,
            }
        )
    return out


@mcp.tool()
async def get_history(chat: str, limit: int = 30) -> list:
    """Read recent messages from one chat, newest first.

    chat: a username (@name), numeric id, phone, t.me link, or the chat's display name.
    limit: how many messages to return (default 30).
    """
    client = await _ensure()
    entity = await _resolve(client, chat)
    return [_fmt(m) async for m in client.iter_messages(entity, limit=limit)]


@mcp.tool()
async def search_messages(chat: str, query: str, limit: int = 30) -> list:
    """Search text messages within one chat, newest first.

    chat: a username (@name), numeric id, phone, t.me link, or the chat's display name.
    query: text to search for.
    limit: how many matches to return (default 30).
    """
    client = await _ensure()
    entity = await _resolve(client, chat)
    return [_fmt(m) async for m in client.iter_messages(entity, search=query, limit=limit)]


def _peer_name(entities: dict, peer) -> str | None:
    if peer is None:
        return None
    pid = (
        getattr(peer, "user_id", None)
        or getattr(peer, "channel_id", None)
        or getattr(peer, "chat_id", None)
    )
    ent = entities.get(pid)
    if ent is None:
        return None
    return (
        getattr(ent, "username", None)
        or " ".join(
            p for p in [getattr(ent, "first_name", None), getattr(ent, "last_name", None)] if p
        )
        or getattr(ent, "title", None)
    )


@mcp.tool()
async def search_all(query: str, limit: int = 30) -> list:
    """Search text messages across ALL your chats at once (global search).

    query: text to search for.
    limit: how many matches to return (default 30).
    """
    client = await _ensure()
    result = await client(
        SearchGlobalRequest(
            q=query,
            filter=InputMessagesFilterEmpty(),
            min_date=None,
            max_date=None,
            offset_rate=0,
            offset_peer=InputPeerEmpty(),
            offset_id=0,
            limit=limit,
        )
    )
    entities = {e.id: e for e in [*result.users, *result.chats]}
    out = []
    for m in result.messages:
        out.append(
            {
                "id": m.id,
                "date": m.date.isoformat() if getattr(m, "date", None) else None,
                "chat": _peer_name(entities, getattr(m, "peer_id", None)),
                "from": _peer_name(entities, getattr(m, "from_id", None)),
                "text": getattr(m, "message", "") or "",
            }
        )
    return out


@mcp.tool()
async def send_message(chat: str, text: str) -> dict:
    """Send a text message as yourself. Use deliberately - this posts to a real chat.

    chat: a username (@name), numeric id, phone, t.me link, or the chat's display name.
    text: the message body to send.
    """
    client = await _ensure()
    entity = await _resolve(client, chat)
    sent = await client.send_message(entity, text)
    return {
        "id": sent.id,
        "chat": chat,
        "text": text,
        "date": sent.date.isoformat() if sent.date else None,
    }


if __name__ == "__main__":
    mcp.run()
