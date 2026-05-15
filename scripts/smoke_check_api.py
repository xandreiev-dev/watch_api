import json
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class WatchLookup:
    brand: str
    normalized_name: str


WATCHES = (
    WatchLookup("Garmin", "fenix 7"),
    WatchLookup("Garmin", "venu 2"),
    WatchLookup("Samsung", "galaxy watch6"),
    WatchLookup("Samsung", "galaxy watch7"),
    WatchLookup("Apple", "watch series 9"),
    WatchLookup("Huawei", "watch gt 4"),
    WatchLookup("Google", "pixel watch 3"),
    WatchLookup("OnePlus", "watch 3"),
    WatchLookup("Motorola", "moto watch 120"),
)


def fetch_json(path: str) -> dict:
    with urlopen(f"{BASE_URL}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def check_api_is_running() -> bool:
    try:
        health = fetch_json("/health")
    except HTTPError as exc:
        print(f"API health check failed: HTTP {exc.code}", file=sys.stderr)
        return False
    except URLError as exc:
        print(f"API is not reachable at {BASE_URL}: {exc}", file=sys.stderr)
        print("\nStart it in a separate terminal first:")
        print("python -m uvicorn watch_api.app:app --reload --host 127.0.0.1 --port 8000")
        return False

    if health.get("status") != "ok":
        print(f"API health check returned unexpected payload: {health}", file=sys.stderr)
        return False
    return True


def check_card(card: dict) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    warnings: list[str] = []
    if not card.get("title"):
        missing.append("title")
    if not card.get("image", {}).get("url"):
        missing.append("image.url")
    for block_name in ("display", "navigation", "health", "connectivity"):
        if not isinstance(card.get(block_name), dict):
            missing.append(block_name)
    if not card.get("battery", {}).get("life"):
        warnings.append("battery.life is empty")
    if not card.get("protection", {}).get("water_resistance"):
        warnings.append("protection.water_resistance is empty")
    if not card.get("variants"):
        missing.append("variants")
    return missing, warnings


def main() -> int:
    if not check_api_is_running():
        return 2

    ok_count = 0
    failed = []
    warnings_by_model = []

    for watch in WATCHES:
        query = urlencode({"brand": watch.brand, "normalized_name": watch.normalized_name})
        path = f"/api/watch-card/by-name?{query}"
        label = f"{watch.brand} {watch.normalized_name}"
        try:
            card = fetch_json(path)
        except HTTPError as exc:
            failed.append((label, f"HTTP {exc.code}"))
            continue

        missing, warnings = check_card(card)
        if missing:
            failed.append((label, ", ".join(missing)))
        else:
            ok_count += 1
            print(f"OK {label}: model_id={card['model']['id']}, variants={len(card['variants'])}")
            if warnings:
                warnings_by_model.append((label, ", ".join(warnings)))

    if failed:
        print("\nModels with missing data or lookup failures:")
        for label, reason in failed:
            print(f"- {label}: {reason}")

    if warnings_by_model:
        print("\nModels with empty optional DB-backed fields:")
        for label, reason in warnings_by_model:
            print(f"- {label}: {reason}")

    print(f"\nPassed: {ok_count}/{len(WATCHES)}")
    return 0 if ok_count >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
