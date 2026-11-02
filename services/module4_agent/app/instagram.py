import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

GRAPH_URL = "https://graph.instagram.com"
DEFAULT_API_VERSION = "v25.0"
MAX_MESSAGE_BYTES = 1000
REQUEST_TIMEOUT_SECONDS = 15


class InstagramError(Exception):
    """
    Raised when a message cannot be sent to the Instagram API.
    """


def _env(name: str) -> Optional[str]:
    """
    Reads an environment variable at call time (empty means not set).
    """

    value = os.getenv(name)

    return value if value else None


def local_mode() -> bool:
    """
    True when Instagram Graph is not used (company demo / no Meta app).
    """

    return (_env("META_MODE") or "").lower() == "local"


def webhook_configured() -> bool:
    """
    True when the verify token and the app secret are set.
    """

    return bool(_env("INSTAGRAM_VERIFY_TOKEN")) and bool(
        _env("INSTAGRAM_APP_SECRET")
    )


def sending_configured() -> bool:
    """
    True when the access token for sending messages is set.
    """

    return bool(_env("INSTAGRAM_ACCESS_TOKEN"))


def verify_challenge(
    mode: Optional[str],
    token: Optional[str],
    challenge: Optional[str]
) -> Optional[str]:
    """
    Answers Meta's verification request. Returns the challenge to send
    back, or None if the request must be rejected.
    """

    expected = _env("INSTAGRAM_VERIFY_TOKEN")

    if mode != "subscribe" or not expected or not token or challenge is None:
        return None

    if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        return None

    return challenge


def verify_signature(raw_body: bytes, header: Optional[str]) -> bool:
    """
    Checks the X-Hub-Signature-256 header against the raw request body.
    """

    secret = _env("INSTAGRAM_APP_SECRET")

    if not secret or not header or not header.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    received = header[len("sha256="):]

    return hmac.compare_digest(
        expected.encode("utf-8"),
        received.encode("utf-8")
    )


def parse_incoming_messages(payload: object) -> List[Dict[str, str]]:
    """
    Extracts the text messages sent by users from a webhook payload.
    Echoes (our own messages), deleted messages, non-text events and
    messages sent by the business account itself are ignored.
    """

    events: List[Dict[str, str]] = []

    if not isinstance(payload, dict) or payload.get("object") != "instagram":
        return events

    for entry in payload.get("entry") or []:

        if not isinstance(entry, dict):
            continue

        business_id = str(entry.get("id", ""))

        for item in entry.get("messaging") or []:

            if not isinstance(item, dict):
                continue

            message = item.get("message")

            if not isinstance(message, dict):
                continue

            if message.get("is_echo") or message.get("is_deleted"):
                continue

            text = message.get("text")
            sender = (item.get("sender") or {}).get("id")
            recipient = (item.get("recipient") or {}).get("id")

            if not isinstance(text, str) or not text.strip() or not sender:
                continue

            if str(sender) == business_id or sender == recipient:
                continue

            mid = message.get("mid")

            events.append(
                {
                    "sender_id": str(sender),
                    "recipient_id": str(recipient or ""),
                    "mid": str(mid) if mid else "",
                    "text": text.strip()
                }
            )

    return events


def _take_bytes(text: str, max_bytes: int) -> str:
    """
    Returns the longest prefix of text that fits in max_bytes (UTF-8).
    """

    size = 0
    end = 0

    for index, char in enumerate(text):
        char_size = len(char.encode("utf-8"))

        if size + char_size > max_bytes:
            break

        size += char_size
        end = index + 1

    return text[:end]


def split_text(text: str, max_bytes: int = MAX_MESSAGE_BYTES) -> List[str]:
    """
    Splits a long text into parts of at most max_bytes bytes, breaking at
    spaces or line breaks whenever possible.
    """

    chunks: List[str] = []
    current = ""

    for token in re.split(r"(\s+)", text.strip()):

        if not token:
            continue

        # A single "word" longer than the limit is cut by characters
        while len(token.encode("utf-8")) > max_bytes:
            head = _take_bytes(token, max_bytes)

            if current.strip():
                chunks.append(current.strip())
                current = ""

            chunks.append(head)
            token = token[len(head):]

        if len((current + token).encode("utf-8")) > max_bytes:
            if current.strip():
                chunks.append(current.strip())
            current = token
        else:
            current += token

    if current.strip():
        chunks.append(current.strip())

    return chunks


def send_text(recipient_id: str, text: str) -> dict:
    """
    Sends one text message (at most 1000 bytes) to an Instagram user.
    """

    if local_mode():
        return {"recipient_id": recipient_id, "message_id": "local.simulated"}

    token = _env("INSTAGRAM_ACCESS_TOKEN")

    if not token:
        raise InstagramError("INSTAGRAM_ACCESS_TOKEN is not configured.")

    version = _env("INSTAGRAM_API_VERSION") or DEFAULT_API_VERSION

    body = json.dumps(
        {
            "recipient": {"id": recipient_id},
            "message": {"text": text}
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{GRAPH_URL}/{version}/me/messages",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:300]
        raise InstagramError(
            f"Instagram API returned HTTP {error.code}: {detail}"
        )

    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise InstagramError(f"Could not reach the Instagram API: {error}")


def send_messages(recipient_id: str, text: str) -> int:
    """
    Sends a text, split into several messages if it is too long.
    Returns the number of messages sent.
    """

    parts = split_text(text)

    for part in parts:
        send_text(recipient_id, part)

    return len(parts)