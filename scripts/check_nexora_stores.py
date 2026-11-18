#!/usr/bin/env python3
"""NEXORA release monitor. Only official store URLs and exact app IDs count."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "nexora" / "store-config.json"
STATUS = ROOT / "nexora" / "release-status.json"
TIMEOUT = 12


def fetch(url: str) -> tuple[str, str]:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; NEXORA-StoreReleaseMonitor/1.0)",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.5",
    })
    with urlopen(req, timeout=TIMEOUT) as response:
        return response.geturl(), response.read(1_500_000).decode("utf-8", errors="replace")


def apple_url(bundle_id: str, countries: list[str]) -> str | None:
    if not bundle_id:
        return None
    for country in countries:
        query = urlencode({"bundleId": bundle_id, "country": country.upper(), "entity": "software"})
        url = "https://itunes.apple.com/lookup?" + query
        try:
            _final, body = fetch(url)
            payload = json.loads(body)
            for record in payload.get("results", []):
                if record.get("bundleId") == bundle_id:
                    link = record.get("trackViewUrl", "")
                    if link.startswith("https://apps.apple.com/"):
                        return link
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            print(f"Apple check ({country}): {exc}", file=sys.stderr)
    return None


def play_url(package_id: str, countries: list[str]) -> str | None:
    if not package_id:
        print("Google Play: no verified package ID configured; not guessing.")
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", package_id):
        print("Invalid Android package ID; skip.", file=sys.stderr)
        return None
    for country in countries:
        url = "https://play.google.com/store/apps/details?" + urlencode({
            "id": package_id, "hl": "en", "gl": country.upper()
        })
        try:
            final, body = fetch(url)
            # Only accept a public Google Play details page that still includes
            # the exact requested package and NEXORA as its listed app name.
            # Never treat Play Store search results as proof.
            if ("play.google.com/store/apps/details" in final
                    and package_id in body
                    and re.search(r"<title[^>]*>[^<]*NEXORA[^<]*</title>", body, re.I)):
                return "https://play.google.com/store/apps/details?id=" + quote(package_id)
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"Play check ({country}): {exc}", file=sys.stderr)
    return None


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    state = json.loads(STATUS.read_text(encoding="utf-8"))
    countries = config.get("countries", ["ES", "PL", "US"])

    apple = apple_url(config.get("apple_bundle_id", ""), countries)
    google = play_url(config.get("google_package_id", ""), countries)

    # Positive discoveries persist; a temporary outage cannot unpublish a store.
    changed = False
    for key, verified in (("app_store", apple), ("google_play", google)):
        if verified and (state[key].get("url") != verified or not state[key].get("available")):
            state[key] = {"available": True, "url": verified}
            changed = True
    if not changed:
        print("NEXORA store availability unchanged; no commit.")
        return

    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    available = [name for key, name in (("app_store", "App Store"), ("google_play", "Google Play"))
                 if state[key]["available"]]
    state["message"] = ("NEXORA is now available on " + " and ".join(available) + "!")
    STATUS.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("UPDATED: " + state["message"])


if __name__ == "__main__":
    main()
