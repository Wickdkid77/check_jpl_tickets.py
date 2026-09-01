#!/usr/bin/env python3
"""
Checks JPL's "Explore JPL" open house on Eventbrite for available tickets and
sends a push notification (via ntfy.sh) if tickets become available again.

Instead of guessing from the public page's HTML/text (unreliable -- CTA
buttons like "Reserve a spot" appear regardless of real availability), this
calls the same JSON API the Eventbrite page itself uses to populate the
ticket picker, and reads the `availability.hasAvailableTickets` field
directly -- the same signal Eventbrite's own front-end relies on.

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
EVENT_ID = "1997060604026"
ORGANIZATION_ID = "168770254525"
API_URL = (
    f"https://www.eventbrite.com/e/api/{EVENT_ID}/ticket-information"
    f"?organizationId={ORGANIZATION_ID}&isChild=false&isOnline=false"
    f"&eventTimezone=America%2FLos_Angeles"
)

STATE_FILE = Path("state.json")

# Set this via the NTFY_TOPIC environment variable (see workflow file).
# Pick a hard-to-guess topic name -- anyone who knows it can read your
# notifications, since ntfy topics aren't private by default.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")


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


def fetch_ticket_info() -> requests.Response:
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": EVENT_URL,
        # A realistic browser UA reduces (but doesn't eliminate) the chance
        # of being blocked by bot-protection (this endpoint sits behind an
        # AWS WAF, per the captured request).
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    return requests.get(API_URL, headers=headers, timeout=20)


def classify(data: dict) -> str:
    availability = data.get("availability", {})
    has_available = availability.get("hasAvailableTickets")
    is_sold_out = data.get("isSoldOut")

    if has_available is True:
        return "available"
    if is_sold_out is True or has_available is False:
        return "sold_out"
    # Field missing or unexpected shape -- don't guess.
    return "unclear"


def main() -> int:
    state = load_state()
    last_status = state.get("last_status", "unknown")

    try:
        resp = fetch_ticket_info()
    except requests.RequestException as e:
        print(f"Request failed: {e}")
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
        print("Got HTTP 403 -- likely blocked by bot protection (WAF).")
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
        print(resp.text[:500])
        state["last_status"] = "unclear"
        save_state(state)
        return 0

    try:
        data = resp.json()
    except ValueError:
        print("Response wasn't valid JSON -- API shape may have changed.")
        state["last_status"] = "unclear"
        save_state(state)
        return 0

    status = classify(data)
    print(f"Detected status: {status} (previous: {last_status})")
    print(f"  isSoldOut={data.get('isSoldOut')}  "
          f"hasAvailableTickets={data.get('availability', {}).get('hasAvailableTickets')}  "
          f"hasAvailableHiddenTickets={data.get('availability', {}).get('hasAvailableHiddenTickets')}")

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
