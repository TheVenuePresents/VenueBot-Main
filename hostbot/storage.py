import base64
import json
import logging
import os
import time
from typing import Optional

from .config import (
    DATA_USER_PATH,
    HOSTBOT_DATA_FILE,
    FIREBASE_COLLECTION,
    FIREBASE_CREDENTIALS,
    FIREBASE_PROJECT_ID,
    FIREBASE_DATABASE_URL,
)

try:
    import firebase_admin
    from firebase_admin import credentials, db
except Exception:  # pragma: no cover - firebase is optional
    firebase_admin = None


_realtime_db = None


def _get_realtime_db():
    """Return a Firebase Realtime Database reference if configured."""

    global _realtime_db
    if _realtime_db is not None:
        return _realtime_db
    if not (firebase_admin and FIREBASE_CREDENTIALS and FIREBASE_DATABASE_URL):
        return None
    cred = credentials.Certificate(FIREBASE_CREDENTIALS)
    opts = {"databaseURL": FIREBASE_DATABASE_URL}
    if FIREBASE_PROJECT_ID:
        opts["projectId"] = FIREBASE_PROJECT_ID
    firebase_admin.initialize_app(cred, opts)
    _realtime_db = db.reference(f"/{FIREBASE_COLLECTION}")
    return _realtime_db


def _user_ref(user_id: int):
    """Return the Realtime Database reference for ``user_id`` or ``None``."""

    fb = _get_realtime_db()
    if not fb:
        return None
    return fb.child(str(user_id))


def load_data() -> dict:
    """Return the stored JSON data from file or Firebase."""

    fb = _get_realtime_db()
    if fb:
        try:
            return fb.child("data").get() or {}
        except Exception as exc:  # pragma: no cover - network/cred errors
            logging.error("Firebase read failed: %s", exc)
    try:
        with open(HOSTBOT_DATA_FILE, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logging.error("Invalid JSON data file: %s", HOSTBOT_DATA_FILE)
        return {}


def save_data(data: dict) -> None:
    """Persist ``data`` either to Firebase or the local file."""

    fb = _get_realtime_db()
    if fb:
        try:
            fb.child("data").set(data)
            return
        except Exception as exc:  # pragma: no cover - network/cred errors
            logging.error("Firebase write failed: %s", exc)
    with open(HOSTBOT_DATA_FILE, "w", encoding="utf-8") as fp:
        json.dump(data, fp)


# Zoom name helpers ---------------------------------------------------------


def save_zoom_name_to_file(user_id: int, zoom_name: str) -> str:
    """Save ``zoom_name`` for ``user_id`` and return the base64 encoded value."""

    encoded = base64.b64encode(zoom_name.encode()).decode()
    data = {
        "zoomName": zoom_name,
        "base64": encoded,
        "lastUsed": int(time.time()),
        "telegramId": "",
    }

    doc = _user_ref(user_id)
    if doc:
        try:
            doc.set(data)
            return encoded
        except Exception as exc:  # pragma: no cover - network/cred errors
            logging.error("Firebase write failed: %s", exc)

    store = load_data()
    base = store.setdefault(DATA_USER_PATH, {})
    base[str(user_id)] = data
    save_data(store)
    return encoded


def get_zoom_name_from_file(user_id: int) -> Optional[str]:
    """Return the stored base64 Zoom name for ``user_id``."""

    doc = _user_ref(user_id)
    if doc:
        try:
            data = doc.get()
            if data:
                timestamp = int(time.time())
                doc.update({"lastUsed": timestamp})
                return data.get("base64")
        except Exception as exc:  # pragma: no cover - network/cred errors
            logging.error("Firebase read failed: %s", exc)

    store = load_data()
    user = store.get(DATA_USER_PATH, {}).get(str(user_id))
    if not user:
        return None
    user["lastUsed"] = int(time.time())
    save_data(store)
    return user.get("base64")


def save_host_command_message_id(message_id: int) -> None:
    """Persist the Discord message ID for the host command embed."""

    data = load_data()
    base = data.setdefault(DATA_USER_PATH, {})
    base["host_message"] = {"id": message_id}
    save_data(data)


def load_host_command_message_id() -> Optional[int]:
    """Return the saved host command embed message ID."""

    data = load_data().get(DATA_USER_PATH, {}).get("host_message")
    if not data:
        return None
    msg = data.get("id")
    if msg is None:
        return None
    msg = str(msg)
    return int(msg) if msg.isdigit() else None


def save_room_number(number: str) -> None:
    """Persist the current room number."""

    data = load_data()
    base = data.setdefault(DATA_USER_PATH, {})
    base["room_number"] = str(number)
    save_data(data)


def load_room_number() -> Optional[str]:
    """Return the stored room number if available."""

    data = load_data().get(DATA_USER_PATH, {})
    value = data.get("room_number")
    return str(value) if value else None
