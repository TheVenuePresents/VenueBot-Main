import json
import logging
import os
import ssl

from dotenv import load_dotenv

load_dotenv()

# Path to the JSON file used for local storage
HOSTBOT_DATA_FILE = os.getenv("HOSTBOT_DATA_FILE", "hostbot_data.json")

# Optional thumbnail URL for the host command embed
EMBED_THUMBNAIL_URL = os.getenv("EMBED_THUMBNAIL_URL", "")
# Footer text used on embeds
EMBED_FOOTER_TEXT = " \u25cf TLR Operations"
# Interval in seconds to refresh the host command embed
EMBED_REFRESH_INTERVAL = int(os.getenv("EMBED_REFRESH_INTERVAL", "3600"))
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS", "ServiceAccount.json")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL")
if not FIREBASE_PROJECT_ID and os.path.exists(FIREBASE_CREDENTIALS):
    try:
        with open(FIREBASE_CREDENTIALS, "r", encoding="utf-8") as fp:
            FIREBASE_PROJECT_ID = json.load(fp).get("project_id")
    except Exception:
        FIREBASE_PROJECT_ID = None
FIREBASE_COLLECTION = os.getenv("FIREBASE_COLLECTION", "hostbot")
# TriggerCMD authentication token
TRIGGERCMD_TOKEN = os.getenv("TRIGGERCMD_TOKEN", "")
TRIGGERCMD_VERIFY_SSL = os.getenv("TRIGGERCMD_VERIFY_SSL", "1") != "0"
SSL_CONTEXT = None if TRIGGERCMD_VERIFY_SSL else ssl._create_unverified_context()

# Base path in the data file for storing user data
DATA_USER_PATH = "hostbot"

# Role ID used for enabling the host command
DISCORD_COHOST_ROLE_ID = int(os.getenv("DISCORD_COHOST_ROLE", "0")) or None

# Optional role allowed to access the admin panel
DISCORD_OPS_ROLE_ID = int(os.getenv("DISCORD_OPS_ROLE", "0")) or None

# User IDs with built-in access to OPs admin abilities
OPS_ADMIN_USER_IDS = {
    994515273157709865,
    1030754913778663515,
    1069313174777647105,
}


if not os.path.exists(HOSTBOT_DATA_FILE):
    with open(HOSTBOT_DATA_FILE, "w", encoding="utf-8") as fp:
        json.dump({}, fp)


def configure_logging(level_str: str) -> None:
    """Configure the Python logger using ``level_str``."""

    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def save_config_to_file(token: str, channel_id: int, bot_log_id: int) -> None:
    """Persist Discord settings to ``HOSTBOT_DATA_FILE``."""

    data = load_data()
    base = data.setdefault(DATA_USER_PATH, {})
    base["config"] = {
        "token": token,
        "channel_id": channel_id,
        "log_channel_id": bot_log_id,
    }
    save_data(data)


def load_config_from_file():
    """Return Discord settings from ``HOSTBOT_DATA_FILE``."""

    data = load_data().get(DATA_USER_PATH, {}).get("config")
    if not data:
        return None, None, None
    channel = data.get("channel_id")
    log_channel = data.get("log_channel_id")
    channel = str(channel)
    log_channel = str(log_channel)
    if not channel.isdigit() or not log_channel.isdigit():
        return None, None, None
    return data.get("token"), int(channel), int(log_channel)


def load_config_from_env():
    """Return Discord settings from environment variables."""

    token = os.getenv("DISCORD_BOT_TOKEN")
    channel = os.getenv("DISCORD_CHANNEL_ID")
    log_channel = os.getenv("DISCORD_BOT_LOG")
    channel_id = int(channel) if channel and channel.isdigit() else None
    log_id = int(log_channel) if log_channel and log_channel.isdigit() else None
    return token, channel_id, log_id


# Below imports placed at end to avoid circular deps in storage module
from .storage import load_data, save_data  # noqa: E402
