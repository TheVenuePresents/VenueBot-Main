import json
import logging
import urllib.request
from urllib.error import HTTPError

from .config import SSL_CONTEXT, TRIGGERCMD_TOKEN


def _call_trigger(trigger: str, params: str | None = None) -> bool:
    """Internal helper to send a TriggerCMD request."""

    try:
        if not TRIGGERCMD_TOKEN:
            raise ValueError("TRIGGERCMD_TOKEN environment variable not set")
        payload: dict[str, str | None] = {"computer": "bot", "trigger": trigger}
        if params is not None:
            payload["params"] = params
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://www.triggercmd.com/api/run/triggerSave",
            data=data,
            headers={
                "authorization": f"Bearer {TRIGGERCMD_TOKEN}",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as response:
            response.read()
        return True
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "ignore")
        except Exception:
            body = exc.reason
        logging.error("TriggerCMD %s HTTP %s: %s", trigger, exc.code, body)
        return False
    except Exception as exc:
        logging.error("TriggerCMD %s error: %s", trigger, exc)
        return False


def send_trigger_cmd(encoded_name: str) -> bool:
    """Assign co-host with ``encoded_name``."""

    return _call_trigger("cohost", encoded_name)


def send_host_cmd(encoded_name: str) -> bool:
    """Assign host with ``encoded_name``."""

    return _call_trigger("host", encoded_name)


def send_reclaim_cmd() -> bool:
    """Reclaim host."""

    return _call_trigger("reclaim")


def send_unmute_cmd() -> bool:
    """Unmute the server."""

    return _call_trigger("unmute")


def send_next_track_cmd() -> bool:
    """Skip to the next track."""

    return _call_trigger("next-track")


def send_revoke_cmd(encoded_name: str) -> bool:
    """Revoke co-host with ``encoded_name``."""

    return _call_trigger("revoke", encoded_name)
