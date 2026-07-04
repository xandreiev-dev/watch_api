import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql

if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from watch_api.db import get_connection


BACKUP_DIR = Path(__file__).resolve().parent / "backups"

BOOL_FIELDS = (
    "heart_rate",
    "spo2",
    "ecg",
    "skin_temperature",
    "barometer",
    "altimeter",
    "compass",
    "accelerometer",
    "gyro",
    "gps",
    "nfc",
    "wifi",
    "bluetooth",
)

SAME_SIZE_FIELDS = (
    "display_size_raw",
    "display_resolution",
    "battery_capacity_mah",
    "battery_life",
)

VARIANT_COLUMNS = (
    "id",
    "watch_model_id",
    "variant_name",
    "case_size_mm",
    "case_size_mm_key",
    "case_material",
    "case_material_key",
    "glass_type",
    "connectivity_type",
    "connectivity_key",
    "esim",
    "lte",
    "esim_key",
    "lte_key",
    "display_size_inch",
    "display_size_raw",
    "display_resolution",
    "battery_capacity_mah",
    "battery_life",
    "weight_g",
    "dimensions",
    "heart_rate",
    "spo2",
    "ecg",
    "skin_temperature",
    "barometer",
    "altimeter",
    "compass",
    "accelerometer",
    "gyro",
    "gps",
    "nfc",
    "wifi",
    "bluetooth",
    "quality_score",
    "is_canonical",
    "source_url",
    "source_host",
    "image_url",
    "updated_at",
)

VALID_SIZES_BY_MODEL = {
    ("samsung", "galaxywatch4"): {40, 44},
    ("samsung", "galaxywatch6"): {40, 44},
    ("samsung", "galaxywatch7"): {40, 44},
    ("samsung", "galaxywatch8"): {40, 44},
    ("samsung", "galaxywatch6classic"): {43, 47},
    ("samsung", "galaxywatchultra"): {47},
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill weak variant specs for the most visible watch catalog models."
    )
    parser.add_argument("--limit", type=int, default=50, help="Number of catalog models to inspect.")
    parser.add_argument("--apply", action="store_true", help="Write updates to the database.")
    args = parser.parse_args()

    models = fetch_top_models(args.limit)
    model_ids = [model["watch_model_id"] for model in models]
    variants = fetch_variants(model_ids)
    changes = build_changes(models, variants)

    print(f"top_models={len(models)}")
    print(f"variants_with_changes={len(changes)}")
    print_summary(changes)

    if not args.apply:
        print("dry_run=true")
        return 0

    if not changes:
        print("nothing_to_update=true")
        return 0

    backup_path = write_backup(changes)
    apply_changes(changes)
    print(f"backup={backup_path}")
    print("updated=true")
    return 0


def fetch_top_models(limit: int) -> list[dict[str, Any]]:
    sql = """
        WITH matched AS (
            SELECT
                wm.id AS watch_model_id,
                wm.brand,
                wm.model_name,
                wm.normalized_name,
                COUNT(DISTINCT w.id) AS watch_count
            FROM g_watch w
            JOIN g_watch_model wm
              ON LOWER(REGEXP_REPLACE(COALESCE(w.brand, ''), '[^[:alnum:]]', '')) =
                 LOWER(REGEXP_REPLACE(COALESCE(wm.brand, ''), '[^[:alnum:]]', ''))
             AND LOWER(REGEXP_REPLACE(COALESCE(w.model, ''), '[^[:alnum:]]', '')) =
                 LOWER(REGEXP_REPLACE(COALESCE(wm.normalized_name, ''), '[^[:alnum:]]', ''))
            GROUP BY wm.id, wm.brand, wm.model_name, wm.normalized_name
        )
        SELECT *
        FROM matched
        ORDER BY watch_count DESC, brand ASC, model_name ASC
        LIMIT %s
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (limit,))
            return list(cursor.fetchall())


def fetch_variants(model_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not model_ids:
        return {}

    placeholders = ", ".join(["%s"] * len(model_ids))
    columns = ", ".join(VARIANT_COLUMNS)
    sql = f"""
        SELECT {columns}
        FROM g_watch_variant
        WHERE watch_model_id IN ({placeholders})
        ORDER BY watch_model_id ASC, case_size_mm ASC, quality_score DESC, id ASC
    """
    rows_by_model: dict[int, list[dict[str, Any]]] = defaultdict(list)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, model_ids)
            for row in cursor.fetchall():
                rows_by_model[int(row["watch_model_id"])].append(row)
    return rows_by_model


def build_changes(
    models: list[dict[str, Any]],
    variants: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    for model in models:
        rows = variants.get(int(model["watch_model_id"]), [])
        if not rows:
            continue

        rows_by_size: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            size = int(row["case_size_mm"]) if row.get("case_size_mm") is not None else None
            if size is not None:
                rows_by_size[size].append(row)

        best_by_size = {
            size: max(size_rows, key=completeness_key)
            for size, size_rows in rows_by_size.items()
        }
        shared_booleans = {
            field: "Y"
            for field in BOOL_FIELDS
            if any(is_yes(row.get(field)) for row in rows)
        }

        for row in rows:
            updates: dict[str, Any] = {}
            reasons: list[str] = []

            invalid_size = has_invalid_size(model, row)
            if invalid_size:
                updates.update(
                    {
                        "case_size_mm": None,
                        "quality_score": 0,
                        "is_canonical": 0,
                    }
                )
                reasons.append("invalid_known_size")

            size = int(row["case_size_mm"]) if row.get("case_size_mm") is not None else None
            donor = best_by_size.get(size) if size is not None else None

            should_enrich = not invalid_size and int(row.get("quality_score") or 0) >= 50

            if should_enrich and donor is not None and int(donor["id"]) != int(row["id"]):
                copy_same_size_fields(row, donor, updates, reasons)

            if should_enrich:
                copy_shared_booleans(row, shared_booleans, updates, reasons)

            if not invalid_size:
                normalize_display_size(row, updates, reasons)
                normalize_connectivity(row, updates, reasons)
                lower_empty_high_score(row, updates, reasons)

            if updates:
                changes.append(
                    {
                        "model": {
                            "id": model["watch_model_id"],
                            "brand": model["brand"],
                            "model_name": model["model_name"],
                            "watch_count": model["watch_count"],
                        },
                        "variant_id": row["id"],
                        "variant_name": row["variant_name"],
                        "before": serializable_row(row),
                        "updates": updates,
                        "reasons": sorted(set(reasons)),
                    }
                )

    return changes


def copy_same_size_fields(
    row: dict[str, Any],
    donor: dict[str, Any],
    updates: dict[str, Any],
    reasons: list[str],
) -> None:
    for field in SAME_SIZE_FIELDS:
        if is_empty(row.get(field)) and not is_empty(donor.get(field)):
            updates[field] = donor[field]
            reasons.append("same_size_fill")

    for field in BOOL_FIELDS:
        if is_yes(donor.get(field)) and not is_yes(row.get(field)):
            updates[field] = "Y"
            reasons.append("same_size_booleans")

    raw_type = identity(row.get("connectivity_type"))
    donor_type = normalized_connectivity(donor)
    row_type = normalized_connectivity({**row, **updates})
    can_copy_connectivity = raw_type in {"", "lte", "gsmarenastub"} or row_type in {None, "lte"}

    if can_copy_connectivity:
        for field in ("esim", "lte"):
            if is_yes(donor.get(field)) and not is_yes(row.get(field)):
                updates[field] = "Y"
                reasons.append("same_size_connectivity")

        if connectivity_rank(donor_type) > connectivity_rank(row_type):
            updates["connectivity_type"] = donor_type
            reasons.append("same_size_connectivity")


def copy_shared_booleans(
    row: dict[str, Any],
    shared_booleans: dict[str, str],
    updates: dict[str, Any],
    reasons: list[str],
) -> None:
    for field, value in shared_booleans.items():
        if not is_yes(row.get(field)) and field not in updates:
            updates[field] = value
            reasons.append("model_boolean_fill")


def normalize_display_size(
    row: dict[str, Any],
    updates: dict[str, Any],
    reasons: list[str],
) -> None:
    parsed = display_size_from_raw(row.get("display_size_raw"))
    if parsed is None:
        return

    current = row.get("display_size_inch")
    try:
        current_float = float(current) if current is not None else None
    except (TypeError, ValueError):
        current_float = None

    if current_float is None or abs(current_float - parsed) > 0.01:
        updates["display_size_inch"] = parsed
        reasons.append("display_size_from_raw")


def normalize_connectivity(
    row: dict[str, Any],
    updates: dict[str, Any],
    reasons: list[str],
) -> None:
    merged = {**row, **updates}
    normalized = normalized_connectivity(merged)
    if not normalized:
        return

    current = clean_text(row.get("connectivity_type"))
    if current != normalized:
        updates["connectivity_type"] = normalized
        reasons.append("connectivity_normalized")

    if normalized in {"gps+lte", "lte"}:
        if not is_yes(merged.get("lte")):
            updates["lte"] = "Y"
            reasons.append("connectivity_normalized")
    if normalized not in {"gps+lte", "lte"} and clean_text(row.get("source_host")) == "www.garmin.ru":
        if is_yes(merged.get("lte")):
            updates["lte"] = "N"
            reasons.append("garmin_lte_cleanup")


def lower_empty_high_score(
    row: dict[str, Any],
    updates: dict[str, Any],
    reasons: list[str],
) -> None:
    merged = {**row, **updates}
    has_size = merged.get("case_size_mm") is not None
    has_display = not is_empty(merged.get("display_size_raw")) or not is_empty(merged.get("display_resolution"))
    has_battery = not is_empty(merged.get("battery_capacity_mah")) or not is_empty(merged.get("battery_life"))
    has_any_sensor = any(is_yes(merged.get(field)) for field in BOOL_FIELDS)
    score = int(row.get("quality_score") or 0)

    if score >= 80 and not has_display and not has_battery and not has_any_sensor:
        updates["quality_score"] = 0
        updates["is_canonical"] = 0
        reasons.append("empty_high_score_lowered")


def has_invalid_size(model: dict[str, Any], row: dict[str, Any]) -> bool:
    size = row.get("case_size_mm")
    if size is None:
        return False
    key = (identity(model.get("brand")), identity(model.get("normalized_name") or model.get("model_name")))
    valid_sizes = VALID_SIZES_BY_MODEL.get(key)
    return valid_sizes is not None and int(size) not in valid_sizes


def completeness_key(row: dict[str, Any]) -> tuple[int, int, int, int]:
    score = 0
    score += sum(not is_empty(row.get(field)) for field in SAME_SIZE_FIELDS)
    score += sum(is_yes(row.get(field)) for field in BOOL_FIELDS)
    score += sum(is_yes(row.get(field)) for field in ("esim", "lte"))
    score += 2 if not is_empty(row.get("source_host")) else 0
    score += 2 if not is_empty(row.get("image_url")) else 0
    score += 2 if row.get("case_size_mm") is not None else 0
    return (
        score,
        1 if clean_text(row.get("source_host")) else 0,
        int(row.get("quality_score") or 0),
        int(row.get("id") or 0),
    )


def normalized_connectivity(row: dict[str, Any]) -> str | None:
    raw = identity(row.get("connectivity_type"))
    has_gps = is_yes(row.get("gps")) or "gps" in raw
    has_lte = is_yes(row.get("lte")) or is_yes(row.get("esim")) or any(
        token in raw for token in ("lte", "cellular", "4g", "mobile")
    )
    has_bluetooth = is_yes(row.get("bluetooth")) or "bluetooth" in raw or raw == "bt"

    if has_gps and has_lte:
        return "gps+lte"
    if has_lte:
        return "lte"
    if has_gps and has_bluetooth:
        return "gps+bluetooth"
    if has_gps:
        return "gps"
    if has_bluetooth:
        return "bluetooth"
    if raw == "wifi":
        return "wifi"
    return None


def connectivity_rank(value: str | None) -> int:
    return {
        "gps+lte": 5,
        "lte": 4,
        "gps+bluetooth": 3,
        "gps": 2,
        "bluetooth": 1,
        "wifi": 1,
    }.get(value or "", 0)


def display_size_from_raw(value: Any) -> float | None:
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:\"|inch|in\b)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def apply_changes(changes: list[dict[str, Any]]) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for change in changes:
                updates = dict(change["updates"])
                execute_update(cursor, change["variant_id"], updates)


def execute_update(cursor: Any, variant_id: int, updates: dict[str, Any]) -> None:
    if not updates:
        return

    update_values = dict(updates)
    update_values["updated_at"] = datetime.now()
    set_sql = ", ".join(f"{field} = %s" for field in update_values)
    params = list(update_values.values()) + [variant_id]
    try:
        cursor.execute(
            f"UPDATE g_watch_variant SET {set_sql} WHERE id = %s",
            params,
        )
    except pymysql.err.IntegrityError as exc:
        if exc.args and exc.args[0] == 1062 and "connectivity_type" in updates:
            retry_updates = dict(updates)
            retry_updates.pop("connectivity_type", None)
            execute_update(cursor, variant_id, retry_updates)
            return
        raise


def write_backup(changes: list[dict[str, Any]]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"watch_variant_specs_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(changes, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def print_summary(changes: list[dict[str, Any]]) -> None:
    by_reason: dict[str, int] = defaultdict(int)
    by_model: dict[str, int] = defaultdict(int)
    for change in changes:
        model = change["model"]
        by_model[f"{model['brand']} {model['model_name']}"] += 1
        for reason in change["reasons"]:
            by_reason[reason] += 1

    print("reasons=" + json.dumps(dict(sorted(by_reason.items())), ensure_ascii=False))
    print("models=" + json.dumps(dict(list(sorted(by_model.items()))[:20]), ensure_ascii=False))
    for change in changes[:20]:
        model = change["model"]
        print(
            f"- {model['brand']} {model['model_name']} "
            f"variant={change['variant_id']} reasons={','.join(change['reasons'])} "
            f"updates={change['updates']}"
        )


def serializable_row(row: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            output[key] = float(value)
        elif isinstance(value, datetime):
            output[key] = value.isoformat(sep=" ")
        else:
            output[key] = value
    return output


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() == "null":
        return None
    return text


def is_empty(value: Any) -> bool:
    return clean_text(value) is None


def is_yes(value: Any) -> bool:
    return clean_text(value) in {"Y", "y", "1", "true", "True", "yes", "YES"}


def identity(value: Any) -> str:
    text = clean_text(value) or ""
    return re.sub(r"[^0-9a-z]+", "", text.casefold())


if __name__ == "__main__":
    raise SystemExit(main())
