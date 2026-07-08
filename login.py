"""One-time interactive login for the Telegram MCP server.

Run once:  .venv\\Scripts\\python.exe login.py

It asks for your api_id / api_hash (from https://my.telegram.org), then your
phone number, the login code Telegram sends you, and your 2FA password if you
have one. It writes API_ID, API_HASH, and a reusable SESSION_STRING to .env.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

ENV = Path(__file__).with_name(".env")
load_dotenv(ENV)


def get(name: str, prompt_text: str, cast=str):
    value = os.getenv(name)
    if not value:
        value = input(prompt_text).strip()
    return cast(value)


def main() -> None:
    print("Telegram MCP - one-time login\n")
    print("First get api_id and api_hash from https://my.telegram.org")
    print("  -> log in -> 'API development tools' -> create an app.\n")

    api_id = get("API_ID", "api_id: ", int)
    api_hash = get("API_HASH", "api_hash: ")
    existing = os.getenv("SESSION_STRING") or None

    with TelegramClient(StringSession(existing), api_id, api_hash) as client:
        me = client.get_me()
        session_string = client.session.save()
        print(f"\nLogged in as {me.first_name} (@{me.username}).")

    ENV.write_text(
        f"API_ID={api_id}\nAPI_HASH={api_hash}\nSESSION_STRING={session_string}\n",
        encoding="utf-8",
    )
    print(f"Saved credentials + session to {ENV}")
    print("Keep this .env file private - the session string is like a password.")


if __name__ == "__main__":
    main()
