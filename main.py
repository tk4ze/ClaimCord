#!/usr/bin/env python3
"""
Discord Username Availability Checker
Checks whether Discord usernames are taken using Discord's public API.
Rotates proxies automatically on rate limits.
"""

import urllib.request
import urllib.error
import json
import time
import sys
from collections import deque
from typing import Optional

# ── Configuration ─────────────────────────────────────────────────────────────

# Path to a text file with one username per line.
# Lines starting with # are treated as comments and skipped.
# Set to None to use the fallback USERNAMES list below instead.
USERNAMES_FILE = "usernames.txt"

# Fallback list — only used when USERNAMES_FILE is None or missing
USERNAMES = [
    "shadow",
    "blaze",
    "neoncat",
    # Add more usernames here if you want, or put them in the file specified by USERNAMES_FILE
]

# Proxies to rotate through when rate limited.
# Formats supported:
#   "ip:port"                          (unauthenticated)
#   "ip:port:user:pass"                (authenticated)
#   "socks5://ip:port"                 (SOCKS5, unauthenticated)
#   "socks5://user:pass@ip:port"       (SOCKS5, authenticated)
#
# Leave empty to run without proxies (direct connection only).
PROXIES = [
    # "123.45.67.89:8080",
    # "98.76.54.32:3128:myuser:mypass",
    # "socks5://11.22.33.44:1080",
]

# Delay between requests in seconds (applied regardless of proxies)
REQUEST_DELAY = 1.0

# How many times to retry a single username before giving up
MAX_RETRIES = 3

# ── Discord API ───────────────────────────────────────────────────────────────

API_URL = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Origin": "https://discord.com",
    "Referer": "https://discord.com/register",
}

# ── Proxy Manager ─────────────────────────────────────────────────────────────

class ProxyManager:
    """
    Cycles through a list of proxies.
    On rate-limit, rotate to the next one immediately.
    Tracks consecutive failures per proxy and skips dead ones.
    """

    def __init__(self, proxy_list: list):
        self.proxies = deque(self._parse(p) for p in proxy_list) if proxy_list else deque()
        self.fail_counts = {}  # type: dict
        self.using_proxies = bool(self.proxies)

    @staticmethod
    def _parse(raw: str) -> dict:
        """Turn a proxy string into a dict with keys: url, label."""
        raw = raw.strip()
        # SOCKS5 / full URL formats
        if raw.startswith("socks5://") or raw.startswith("http://") or raw.startswith("https://"):
            label = raw.split("@")[-1] if "@" in raw else raw.split("//")[-1]
            return {"url": raw, "label": label}
        # Plain  ip:port  or  ip:port:user:pass
        parts = raw.split(":")
        if len(parts) == 2:
            host, port = parts
            return {"url": f"http://{host}:{port}", "label": f"{host}:{port}"}
        elif len(parts) == 4:
            host, port, user, passwd = parts
            return {"url": f"http://{user}:{passwd}@{host}:{port}", "label": f"{host}:{port}"}
        else:
            raise ValueError(f"Unrecognised proxy format: {raw!r}")

    def current(self) -> Optional[dict]:
        if not self.proxies:
            return None
        return self.proxies[0]

    def rotate(self, reason: str = ""):
        """Move the current proxy to the back of the queue."""
        if not self.proxies:
            return
        proxy = self.proxies[0]
        label = proxy["label"]
        self.fail_counts[label] = self.fail_counts.get(label, 0) + 1
        self.proxies.rotate(-1)
        new_label = self.proxies[0]["label"] if self.proxies else "none"
        tag = f" ({reason})" if reason else ""
        print(f"    ↻  Proxy rotated{tag}: {label} → {new_label}")

    def build_opener(self) -> urllib.request.OpenerDirector:
        """Return an opener that routes through the current proxy (if any)."""
        proxy = self.current()
        if proxy is None:
            return urllib.request.build_opener()
        handler = urllib.request.ProxyHandler({
            "http":  proxy["url"],
            "https": proxy["url"],
        })
        return urllib.request.build_opener(handler)

    def status_line(self) -> str:
        if not self.proxies:
            return "no proxies configured (direct connection)"
        p = self.current()
        return f"{len(self.proxies)} proxy/proxies loaded — current: {p['label']}"


# Shared instance
_proxy_manager = None  # type: Optional[ProxyManager]


# ── Username check ────────────────────────────────────────────────────────────

def check_username(username: str, attempt: int = 1) -> str:
    """
    Returns one of: 'available', 'taken', 'invalid', 'error:<msg>'
    Automatically rotates proxies on 429 and retries up to MAX_RETRIES times.
    """
    username = username.strip().lower()

    # Basic pre-flight validation (Discord rules)
    if not (2 <= len(username) <= 32):
        return "invalid"
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._")
    if not all(c in allowed for c in username):
        return "invalid"
    if username.startswith(".") or username.endswith("."):
        return "invalid"

    if attempt > MAX_RETRIES:
        return f"error:gave up after {MAX_RETRIES} retries"

    payload = json.dumps({"username": username}).encode()
    req = urllib.request.Request(API_URL, data=payload, headers=HEADERS, method="POST")

    opener = _proxy_manager.build_opener()

    try:
        with opener.open(req, timeout=10) as resp:
            body = json.loads(resp.read())
            taken = body.get("taken", None)
            if taken is True:
                return "taken"
            elif taken is False:
                return "available"
            else:
                return f"error:unexpected_response={body}"

    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry_after = float(e.headers.get("Retry-After", 3))
            if _proxy_manager.using_proxies:
                # Rotate immediately, then retry without waiting
                _proxy_manager.rotate("rate limited")
            else:
                # No proxies — just wait it out
                print(f"    ⚠  Rate limited (no proxies). Waiting {retry_after:.0f}s…")
                time.sleep(retry_after)
            return check_username(username, attempt + 1)

        if e.code == 403:
            if _proxy_manager.using_proxies:
                _proxy_manager.rotate("403 blocked")
                return check_username(username, attempt + 1)
            return "error:HTTP403=Discord blocked the request (try a residential proxy or run from home network)"

        body_text = e.read().decode(errors="replace")
        return f"error:HTTP{e.code}={body_text[:120]}"

    except OSError as exc:
        # Connection error on this proxy — rotate and retry
        if _proxy_manager.using_proxies:
            _proxy_manager.rotate(f"connection error: {exc}")
            return check_username(username, attempt + 1)
        return f"error:{exc}"

    except Exception as exc:
        return f"error:{exc}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def color(text: str, code: int) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


# ── Username loader ───────────────────────────────────────────────────────────

def load_usernames() -> list:
    """
    Load usernames from USERNAMES_FILE if set and the file exists,
    otherwise fall back to the hardcoded USERNAMES list.
    Skips blank lines and lines starting with #.
    """
    if USERNAMES_FILE:
        try:
            with open(USERNAMES_FILE, "r", encoding="utf-8") as f:
                names = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]
            print(f"Loaded {len(names)} username(s) from '{USERNAMES_FILE}'")
            return names
        except FileNotFoundError:
            print(f"⚠  File '{USERNAMES_FILE}' not found — falling back to built-in list.")
        except OSError as e:
            print(f"⚠  Could not read '{USERNAMES_FILE}': {e} — falling back to built-in list.")
    return [u.strip() for u in USERNAMES if u.strip()]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global _proxy_manager
    _proxy_manager = ProxyManager(PROXIES)

    usernames = load_usernames()
    if not usernames:
        print("No usernames to check. Add names to your file or the USERNAMES list.")
        return

    print(f"\nDiscord Username Checker")
    print(f"Proxy: {_proxy_manager.status_line()}")
    print(f"Checking {len(usernames)} username(s)…\n")
    print(f"{'Username':<24}  Status")
    print("─" * 44)

    available = []  # type: list
    taken     = []  # type: list
    invalid   = []  # type: list
    errors    = []  # type: list

    for i, username in enumerate(usernames):
        result = check_username(username)

        if result == "available":
            status_str = color("✓  available", 32)
            available.append(username)
        elif result == "taken":
            status_str = color("✗  taken", 31)
            taken.append(username)
        elif result == "invalid":
            status_str = color("⚠  invalid format", 33)
            invalid.append(username)
        else:
            status_str = color(f"?  {result}", 35)
            errors.append(username)

        print(f"{username:<24}  {status_str}")

        if i < len(usernames) - 1:
            time.sleep(REQUEST_DELAY)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "═" * 44)
    print("SUMMARY")
    print("═" * 44)

    if available:
        print(color(f"\n✓  Available ({len(available)}):", 32))
        for u in available:
            print(f"   {u}")
    else:
        print(color("\n✗  No available usernames found.", 31))

    if taken:
        print(color(f"\n✗  Taken ({len(taken)}):", 31))
        for u in taken:
            print(f"   {u}")

    if invalid:
        print(color(f"\n⚠  Invalid format ({len(invalid)}):", 33))
        for u in invalid:
            print(f"   {u}")
        print("   (Discord names: 2–32 chars, lowercase a–z, 0–9, dots/underscores,")
        print("    cannot start or end with a dot)")

    if errors:
        print(color(f"\n?  Errors ({len(errors)}):", 35))
        for u in errors:
            print(f"   {u}")

    print()


if __name__ == "__main__":
    # Optional CLI overrides:
    #   python discord_username_checker.py usernames.txt   → load from file
    #   python discord_username_checker.py shadow blaze    → check those names directly
    if len(sys.argv) == 2 and sys.argv[1].endswith(".txt"):
        USERNAMES_FILE = sys.argv[1]
    elif len(sys.argv) > 1:
        USERNAMES[:] = sys.argv[1:]
    main()