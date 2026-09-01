#!/usr/bin/env python3
"""
Checks the Eventbrite listing for JPL's "Explore JPL" open house and sends a
push notification (via ntfy.sh) if tickets appear to be available again.

State (whether tickets looked available on the last run) is persisted to
state.json so we only notify on a *transition* from sold-out -> available,
instead of spamming you every 5 minutes while tickets stay open.
"""

import json
import os
import sys
from pathlib import Path

import requests

EVENT_URL = "https://www.eventbrite.com/e/explore-jpl-2026-tickets-1997060604026"
STATE_FILE = Path("state.json")

# Set this via the NTFY_TOPIC environment variable (see workflow file).
# Pick a hard-to-guess topic name -- anyone who knows it can read your
# notifications, since ntfy topics aren't private by default.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")

# Phrases that strongly suggest the event is still sold out.
SOLD_OUT_PHRASES = [
    "sold out",
    "this event is sold out",
    "tickets are no longer available",
]

# Phrases that suggest tickets can currently be selected/reserved.
AVAILABLE_PHRASES = [
    "select a date",
    "select quantity",
    "reserve tickets",
    "get tickets",
    "checkout",
]


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"last_status": "unknown"}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def notify(message: str, title: str, priority: str = "default") -> None:
    if not NTFY_TOPIC:
        print("NTFY_TOPIC not set -- skipping notification. Message was:")
        print(message)
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": priority,
                "Click": EVENT_URL,
            },
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"Failed to send notification: {e}")
 

def fetch_page() -> requests.Response:
    headers = {
        # A realistic browser UA reduces (but doesn't eliminate) the chance
        # of being blocked by bot-protection.
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    return requests.get(EVENT_URL, headers=headers, timeout=20)


def classify(html: str) -> str:
    lower = html.lower()
    has_sold_out = any(p in lower for p in SOLD_OUT_PHRASES)
    has_available = any(p in lower for p in AVAILABLE_PHRASES)

    if has_sold_out and not has_available:
        return "sold_out"
    if has_available and not has_sold_out:
        return "available"
    # Ambiguous -- both or neither phrase set matched. Treat cautiously.
    return "unclear"


def main() -> int:
    state = load_state()
    last_status = state.get("last_status", "unknown")

    try:
        resp = fetch_page()
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        # Don't spam on transient network errors, but do surface repeated
        # failures so you know the checker itself might be broken.
        fail_count = state.get("fail_count", 0) + 1
        state["fail_count"] = fail_count
        save_state(state)
        if fail_count in (5, 20):  # ~25 min in, then ~100 min in
            notify(
                f"The checker has failed {fail_count} times in a row "
                f"({e}). It may be blocked -- worth checking manually.",
                title="JPL ticket checker: repeated errors",
            )
        return 0

    state["fail_count"] = 0

    if resp.status_code == 403:
        print("Got HTTP 403 -- likely blocked by bot protection.")
        if last_status != "blocked":
            notify(
                "Eventbrite is blocking the automated checker (HTTP 403). "
                "You'll need to check the page manually for now.",
                title="JPL ticket checker: blocked",
            )
        state["last_status"] = "blocked"
        save_state(state)
        return 0

    if resp.status_code != 200:
        print(f"Unexpected status code: {resp.status_code}")
        state["last_status"] = "unclear"
        save_state(state)
        return 0

    status = classify(resp.text)
    print(f"Detected status: {status} (previous: {last_status})")

    if status == "available" and last_status != "available":
        notify(
            "Tickets may have opened up for Explore JPL (Oct 10-11)! "
            "Go grab them now, before they're gone again.",
            title="JPL tickets may be available!",
            priority="urgent",
        )

    state["last_status"] = status
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
