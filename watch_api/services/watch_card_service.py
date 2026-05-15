import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from watch_api.db import get_connection


RAW_EXTRA_FIELDS = (
    "battery_life_gps",
    "battery_life_training",
    "launch_price",
    "sleep_tracking",
    "sport_modes",
    "vo2_max",
    "glonass",
    "galileo",
    "beidou",
    "solar_charging",
    "ant_plus",
    "android_compatible",
    "ios_compatible",
)

HIDDEN_VARIANT_NAMES = {"standard", "default", "base"}
SAMSUNG_MODEL_SIZE_WHITELIST = {
    "galaxywatch6": {40.0, 44.0},
    "galaxywatch7": {40.0, 44.0},
    "galaxywatchultra": {47.0},
}


def get_card_by_model_id(model_id: int) -> dict[str, Any]:
    model = _fetch_model_by_id(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Watch model not found")

    variants = _fetch_variants(model_id)
    if not variants:
        raise HTTPException(status_code=404, detail="Watch variants not found")

    return build_watch_card(model, variants)


def get_card_by_name(brand: str, normalized_name: str) -> dict[str, Any]:
    model = _fetch_model_by_name(brand, normalized_name)
    if model is None:
        raise HTTPException(status_code=404, detail="Watch model not found")

    variants = _fetch_variants(model["id"])
    if not variants:
        raise HTTPException(status_code=404, detail="Watch variants not found")

    return build_watch_card(model, variants)


def search_cards(q: str | None, brand: str | None, limit: int) -> list[dict[str, Any]]:
    normalized_limit = max(1, min(limit, 100))
    models = _search_models(q, brand, normalized_limit)

    items: list[dict[str, Any]] = []
    for model in models:
        variants = _fetch_variants(model["id"])
        response_variants = prepare_response_variants(model, variants)
        main_variant = choose_main_variant(response_variants) if response_variants else None
        items.append(
            {
                "id": model["id"],
                "brand": _clean_value(model.get("brand")),
                "model_name": _clean_value(model.get("model_name")),
                "normalized_name": _clean_value(model.get("normalized_name")),
                "image_url": _clean_value(main_variant.get("image_url")) if main_variant else None,
                "battery_life": _clean_value(main_variant.get("battery_life")) if main_variant else None,
                "display_resolution": _clean_value(main_variant.get("display_resolution")) if main_variant else None,
                "water_resistance": _clean_value(model.get("water_resistance")),
            }
        )

    return items


def build_watch_card(model: dict[str, Any], variants: list[dict[str, Any]]) -> dict[str, Any]:
    response_variants = prepare_response_variants(model, variants)
    if not response_variants:
        raise HTTPException(status_code=404, detail="Usable watch variants not found")
    response_variants = _prune_response_variants(model, response_variants)
    if not response_variants:
        raise HTTPException(status_code=404, detail="Usable watch variants not found")
    main_variant = choose_main_variant(response_variants)
    main_variant_id = _int_or_zero(main_variant.get("id"))
    response_variants = _filter_useful_response_variants(model, main_variant, response_variants)
    sorted_variants = sorted(
        response_variants,
        key=lambda variant: (
            _int_or_zero(variant.get("id")) != main_variant_id,
            _variant_response_sort_key(variant),
        ),
    )
    title = build_model_title(model.get("brand"), model.get("model_name"))
    water_resistance = (
        _normalize_water_resistance(model.get("water_resistance"))
        or _extract_water_resistance_from_raw(main_variant.get("raw_payload_json"))
        or _model_water_resistance_fallback(model)
    )
    battery_life = _battery_life_value(main_variant)
    incomplete_warnings = _card_incomplete_warnings(model, main_variant, water_resistance, battery_life)

    return {
        "model": {
            "id": model["id"],
            "brand": _text_value(model.get("brand")),
            "model_name": _text_value(model.get("model_name")),
            "normalized_name": _text_value(model.get("normalized_name")),
            "announce_date": _serialize_value(model.get("announce_date")),
            "os": _text_value(model.get("os")),
            "cpu": _text_value(model.get("cpu")),
            "gpu": _text_value(model.get("gpu")),
            "ram": _text_value(model.get("ram")),
            "storage": _text_value(model.get("storage")),
        },
        "title": title,
        "image": {
            "url": _clean_value(main_variant.get("image_url")),
            "has_image_data": bool(main_variant.get("image_data")),
        },
        "display": {
            "type": _clean_value(model.get("display_type")),
            "size_inch": _display_size_inch(main_variant),
            "size_raw": _clean_value(main_variant.get("display_size_raw")),
            "resolution": _clean_value(main_variant.get("display_resolution")),
        },
        "materials": {
            "case_material": _clean_value(main_variant.get("case_material")),
            "glass_type": _clean_value(main_variant.get("glass_type")),
        },
        "battery": {
            "capacity_mah": _serialize_value(main_variant.get("battery_capacity_mah")),
            "life": battery_life,
        },
        "protection": {
            "water_resistance": water_resistance,
        },
        "navigation": {
            "gps": _yn_bool(main_variant.get("gps")),
            "compass": _yn_bool(main_variant.get("compass")),
            "altimeter": _yn_bool(main_variant.get("altimeter")),
            "barometer": _yn_bool(main_variant.get("barometer")),
        },
        "health": {
            "heart_rate": _yn_bool(main_variant.get("heart_rate")),
            "spo2": _yn_bool(main_variant.get("spo2")),
            "ecg": _yn_bool(main_variant.get("ecg")),
            "skin_temperature": _yn_bool(main_variant.get("skin_temperature")),
        },
        "connectivity": {
            "type": _normalize_connectivity_type(main_variant),
            "connectivity_type": _normalize_connectivity_type(main_variant),
            "bluetooth": _yn_bool(main_variant.get("bluetooth")),
            "wifi": _yn_bool(main_variant.get("wifi")),
            "nfc": _yn_bool(main_variant.get("nfc")),
            "lte": _connectivity_bool(main_variant, "lte"),
            "esim": _connectivity_bool(main_variant, "esim"),
        },
        "main_variant": _build_main_variant(model, main_variant, is_canonical=True),
        "variants": [
            _build_variant_summary(
                model,
                variant,
                is_canonical=_int_or_zero(variant.get("id")) == main_variant_id,
            )
            for variant in sorted_variants
        ],
        "source": {
            "host": _clean_value(main_variant.get("source_host")),
            "url": _clean_value(main_variant.get("source_url")),
        },
        "raw_extra": extract_raw_extra(main_variant.get("raw_payload_json")),
        "incomplete": _is_card_incomplete_for_ui(model, incomplete_warnings),
        "warnings": incomplete_warnings,
    }


def choose_main_variant(variants: list[dict[str, Any]]) -> dict[str, Any]:
    return max(variants, key=_main_variant_sort_key)


def prepare_response_variants(
    model: dict[str, Any],
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for variant in variants:
        if _is_junk_variant(model, variant):
            continue
        key = _variant_identity_key(model, variant)
        current = best_by_key.get(key)
        if current is None or _dedupe_variant_sort_key(variant) > _dedupe_variant_sort_key(current):
            best_by_key[key] = variant
    return list(best_by_key.values())


def _prune_response_variants(model: dict[str, Any], variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usable = [variant for variant in variants if not _is_low_value_response_variant(model, variant)]
    if not usable:
        usable = variants

    if any(_clean_value(variant.get("case_size_mm")) is not None for variant in usable):
        usable = [variant for variant in usable if _clean_value(variant.get("case_size_mm")) is not None]

    best_by_display_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for variant in usable:
        key = _display_variant_key(model, variant)
        current = best_by_display_key.get(key)
        if current is None or _dedupe_variant_sort_key(variant) > _dedupe_variant_sort_key(current):
            best_by_display_key[key] = variant
    return list(best_by_display_key.values())


def _is_low_value_response_variant(model: dict[str, Any], variant: dict[str, Any]) -> bool:
    effective_score = _effective_quality_score(model, variant)
    if effective_score <= 0 and _int_or_zero(variant.get("is_canonical")) != 1:
        return True
    if effective_score < 50 and _clean_value(variant.get("case_size_mm")) is None:
        return True
    return False


def _display_variant_key(model: dict[str, Any], variant: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _variant_key_value(variant, "case_size_mm_key", "case_size_mm"),
        _identity_text(_visible_variant_name(model, variant.get("variant_name"))) or "__base__",
        _variant_key_value(variant, "case_material_key", "case_material"),
        _variant_key_value(variant, "", "glass_type"),
    )


def build_model_title(brand: Any, model_name: Any) -> str:
    brand_text = str(_clean_value(brand) or "").strip()
    model_text = str(_clean_value(model_name) or "").strip()

    if not brand_text:
        return model_text
    if not model_text:
        return brand_text
    if brand_text.casefold() in model_text.casefold():
        return model_text
    return f"{brand_text} {model_text}"


def build_variant_display_name(model: dict[str, Any], variant_name: Any) -> str:
    title = build_model_title(model.get("brand"), model.get("model_name"))
    variant_text = _visible_variant_name(model, variant_name)
    if not variant_text:
        return title
    return f"{title} {variant_text}"


def extract_raw_extra(raw_payload_json: Any) -> dict[str, Any]:
    payload = _parse_raw_payload(raw_payload_json)
    if not isinstance(payload, dict):
        return {}

    raw_extra: dict[str, Any] = {}
    for field in RAW_EXTRA_FIELDS:
        value = _find_raw_value(payload, field)
        cleaned = _clean_value(value)
        if cleaned is not None:
            raw_extra[field] = _serialize_value(cleaned)
    return raw_extra


def _fetch_model_by_id(model_id: int) -> dict[str, Any] | None:
    sql = """
        SELECT
            id, brand, model_name, normalized_name, announce_date, os, cpu, gpu,
            ram, storage, display_type, water_resistance, created_at, updated_at
        FROM g_watch_model
        WHERE id = %s
        LIMIT 1
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (model_id,))
            return cursor.fetchone()


def _fetch_model_by_name(brand: str, normalized_name: str) -> dict[str, Any] | None:
    sql = """
        SELECT
            id, brand, model_name, normalized_name, announce_date, os, cpu, gpu,
            ram, storage, display_type, water_resistance, created_at, updated_at
        FROM g_watch_model
        WHERE LOWER(brand) = LOWER(%s)
          AND LOWER(normalized_name) = LOWER(%s)
        ORDER BY id ASC
        LIMIT 1
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (brand, normalized_name))
            return cursor.fetchone()


def _fetch_variants(model_id: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            id, watch_model_id, variant_name, case_size_mm, case_material,
            glass_type, connectivity_type, esim, lte, display_size_inch,
            display_size_raw, display_resolution, battery_capacity_mah,
            battery_life, weight_g, dimensions, heart_rate, spo2, ecg,
            skin_temperature, barometer, altimeter, compass, accelerometer,
            gyro, gps, nfc, wifi, bluetooth, quality_score, is_canonical,
            created_at, updated_at, case_size_mm_key, case_material_key,
            connectivity_key, esim_key, lte_key, source_url, source_host,
            image_url, image_data, raw_payload_json
        FROM g_watch_variant
        WHERE watch_model_id = %s
        ORDER BY
            is_canonical DESC,
            quality_score DESC,
            case_size_mm ASC,
            variant_name ASC,
            id ASC
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (model_id,))
            return list(cursor.fetchall())


def _search_models(q: str | None, brand: str | None, limit: int) -> list[dict[str, Any]]:
    where_clauses: list[str] = []
    params: list[Any] = []

    if q:
        pattern = f"%{q.casefold()}%"
        where_clauses.append(
            "(LOWER(model_name) LIKE %s OR LOWER(normalized_name) LIKE %s OR LOWER(brand) LIKE %s)"
        )
        params.extend([pattern, pattern, pattern])

    if brand:
        where_clauses.append("LOWER(brand) = LOWER(%s)")
        params.append(brand)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"""
        SELECT
            id, brand, model_name, normalized_name, announce_date, os, cpu, gpu,
            ram, storage, display_type, water_resistance, created_at, updated_at
        FROM g_watch_model
        {where_sql}
        ORDER BY brand ASC, model_name ASC, id ASC
        LIMIT %s
    """
    params.append(limit)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())


def _build_main_variant(
    model: dict[str, Any],
    variant: dict[str, Any],
    is_canonical: bool,
) -> dict[str, Any]:
    return {
        "id": variant["id"],
        "variant_name": _visible_variant_name(model, variant.get("variant_name")),
        "display_name": build_variant_display_name(model, variant.get("variant_name")),
        "case_size_mm": _serialize_value(variant.get("case_size_mm")),
        "quality_score": _effective_quality_score(model, variant),
        "is_canonical": is_canonical,
        "source_url": _clean_value(variant.get("source_url")),
        "source_host": _clean_value(variant.get("source_host")),
    }


def _build_variant_summary(
    model: dict[str, Any],
    variant: dict[str, Any],
    is_canonical: bool,
) -> dict[str, Any]:
    return {
        "id": variant["id"],
        "variant_name": _visible_variant_name(model, variant.get("variant_name")),
        "display_name": build_variant_display_name(model, variant.get("variant_name")),
        "case_size_mm": _serialize_value(variant.get("case_size_mm")),
        "case_material": _clean_value(variant.get("case_material")),
        "glass_type": _clean_value(variant.get("glass_type")),
        "connectivity_type": _normalize_connectivity_type(variant),
        "battery_life": _battery_life_value(variant),
        "quality_score": _effective_quality_score(model, variant),
        "is_canonical": is_canonical,
    }


def _visible_variant_name(model: dict[str, Any], value: Any) -> str | None:
    cleaned = _clean_value(value)
    if cleaned is None:
        return None
    variant_text = str(cleaned).strip()
    for _ in range(3):
        before = variant_text
        for prefix in _variant_name_prefixes(model):
            variant_text = _strip_text_prefix(variant_text, prefix)
        if variant_text == before:
            break

    variant_text = variant_text.strip(" -+/,_")
    if not variant_text or variant_text.casefold() in HIDDEN_VARIANT_NAMES:
        return None
    return variant_text


def _variant_name_prefixes(model: dict[str, Any]) -> list[str]:
    return [
        str(value).strip()
        for value in (
            build_model_title(model.get("brand"), model.get("model_name")),
            model.get("model_name"),
            model.get("normalized_name"),
        )
        if _clean_value(value)
    ]


def _strip_text_prefix(text: str, prefix: str) -> str:
    if not prefix:
        return text
    pattern = rf"^\s*{re.escape(prefix)}(?:\s+|[-+/,_]+|$)"
    stripped = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return stripped if stripped != text else text


def _variant_identity_key(model: dict[str, Any], variant: dict[str, Any]) -> tuple[Any, ...]:
    key = (
        _variant_key_value(variant, "case_size_mm_key", "case_size_mm"),
        _variant_key_value(variant, "case_material_key", "case_material"),
        _variant_key_value(variant, "", "glass_type"),
        _connectivity_key_value(model, variant),
        _variant_key_value(variant, "esim_key", "esim"),
        _variant_key_value(variant, "lte_key", "lte"),
    )
    if _identity_text(model.get("brand")) == "samsung":
        return key
    return ((_identity_text(_visible_variant_name(model, variant.get("variant_name"))) or "__base__"), *key)


def _variant_key_value(variant: dict[str, Any], key_field: str, fallback_field: str) -> str:
    if key_field:
        return _identity_text(variant.get(key_field)) or _identity_text(variant.get(fallback_field))
    return _identity_text(variant.get(fallback_field))


def _connectivity_key_value(model: dict[str, Any], variant: dict[str, Any]) -> str:
    normalized = _normalize_connectivity_type(variant)
    if _identity_text(model.get("brand")) == "samsung" and normalized in {"lte", "gps+lte"}:
        return "gpslte"
    return _identity_text(normalized)


def _is_junk_variant(model: dict[str, Any], variant: dict[str, Any]) -> bool:
    if _is_zero_quality_junk(model, variant):
        return True
    if _identity_text(_clean_value(variant.get("connectivity_type"))) == "gsmarenastub":
        return True
    if (
        _identity_text(model.get("brand")) == "samsung"
        and _int_or_zero(variant.get("quality_score")) < 50
        and _clean_value(variant.get("case_size_mm")) is None
    ):
        return True
    if not _is_expected_model_size(model, variant):
        return True
    return False


def _is_zero_quality_junk(model: dict[str, Any], variant: dict[str, Any]) -> bool:
    if _int_or_zero(variant.get("quality_score")) > 0:
        return False
    if _identity_text(model.get("brand")) == "samsung":
        return True
    if _int_or_zero(variant.get("is_canonical")) == 1:
        return False
    if _identity_text(_clean_value(variant.get("connectivity_type"))) == "gsmarenastub":
        return True
    return _variant_completeness_score(variant) < 8 and not (
        _has_value(variant.get("source_url")) or _has_value(variant.get("image_url"))
    )


def _is_expected_model_size(model: dict[str, Any], variant: dict[str, Any]) -> bool:
    brand = _identity_text(model.get("brand"))
    if brand != "samsung":
        return True
    allowed_sizes = SAMSUNG_MODEL_SIZE_WHITELIST.get(_identity_text(model.get("normalized_name")))
    if not allowed_sizes:
        return True
    case_size = _float_value(variant.get("case_size_mm"))
    if case_size is None:
        return False
    return case_size in allowed_sizes


def _filter_useful_response_variants(
    model: dict[str, Any],
    main_variant: dict[str, Any],
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    main_id = _int_or_zero(main_variant.get("id"))
    for variant in variants:
        if _int_or_zero(variant.get("id")) == main_id:
            filtered.append(variant)
            continue
        if _is_redundant_with_main(model, main_variant, variant):
            continue
        filtered.append(variant)
    return filtered


def _is_redundant_with_main(
    model: dict[str, Any],
    main_variant: dict[str, Any],
    variant: dict[str, Any],
) -> bool:
    main_size = _float_value(main_variant.get("case_size_mm"))
    variant_size = _float_value(variant.get("case_size_mm"))
    same_size = main_size is not None and variant_size is not None and main_size == variant_size

    if not _empty_or_same(main_variant.get("case_material"), variant.get("case_material")):
        return False
    if not _empty_or_same(main_variant.get("glass_type"), variant.get("glass_type")):
        return False

    lower_quality = _effective_quality_score(model, variant) < _effective_quality_score(model, main_variant)
    no_battery = _battery_life_value(variant) is None
    weak_payload = not (
        _has_value(variant.get("source_url"))
        or _has_value(variant.get("image_url"))
        or _has_display_data(variant)
    )
    redundant_connectivity = _connectivity_redundant_with_main(main_variant, variant)

    if same_size and redundant_connectivity and no_battery and lower_quality:
        return True

    if no_battery and lower_quality and _normalize_connectivity_type(variant) is None:
        return True

    if weak_payload and no_battery and lower_quality and _normalize_connectivity_type(variant) is None:
        return True

    if _identity_text(model.get("brand")) != "samsung":
        return False

    if (
        _visible_variant_name(model, main_variant.get("variant_name")) is None
        and _visible_variant_name(model, variant.get("variant_name")) is None
    ):
        return True

    if _connectivity_key_value(model, main_variant) == _connectivity_key_value(model, variant):
        return True

    has_source_or_image = _has_value(variant.get("source_url")) or _has_value(variant.get("image_url"))
    return not has_source_or_image and _variant_completeness_score(variant) <= _variant_completeness_score(main_variant)


def _empty_or_same(main_value: Any, variant_value: Any) -> bool:
    main_text = _identity_text(main_value)
    variant_text = _identity_text(variant_value)
    return not variant_text or not main_text or main_text == variant_text


def _connectivity_redundant_with_main(main_variant: dict[str, Any], variant: dict[str, Any]) -> bool:
    main_type = _normalize_connectivity_type(main_variant)
    variant_type = _normalize_connectivity_type(variant)
    if variant_type is None:
        return True
    if main_type == variant_type:
        return True
    main_parts = set(str(main_type or "").split("+"))
    variant_parts = set(str(variant_type or "").split("+"))
    return bool(main_parts) and variant_parts.issubset(main_parts)


def _dedupe_variant_sort_key(variant: dict[str, Any]) -> tuple[int, int, int, int, int, int, datetime, int]:
    return (
        _has_value(_battery_life_value(variant)),
        _variant_completeness_score(variant),
        _connectivity_rank(variant),
        _has_value(variant.get("source_url")),
        _has_value(variant.get("image_url")),
        _int_or_zero(variant.get("quality_score")),
        _datetime_or_min(variant.get("updated_at")),
        _int_or_zero(variant.get("id")),
    )


def _main_variant_sort_key(variant: dict[str, Any]) -> tuple[int, int, int, int, int, int, int, int, int, datetime, int]:
    return (
        _has_value(variant.get("source_url")),
        _has_value(variant.get("image_url")),
        _has_display_data(variant),
        _has_value(_battery_life_value(variant)),
        _variant_completeness_score(variant),
        _connectivity_rank(variant),
        _has_value(variant.get("case_size_mm")),
        _has_normal_connectivity(variant),
        _int_or_zero(variant.get("quality_score")),
        _datetime_or_min(variant.get("updated_at")),
        _int_or_zero(variant.get("id")),
    )


def _variant_response_sort_key(variant: dict[str, Any]) -> tuple[int, int, float, str, int]:
    return (
        -_int_or_zero(variant.get("is_canonical")),
        -_int_or_zero(variant.get("quality_score")),
        _float_or_large(variant.get("case_size_mm")),
        str(_clean_value(variant.get("variant_name")) or "").casefold(),
        _int_or_zero(variant.get("id")),
    )


def _parse_raw_payload(raw_payload_json: Any) -> Any:
    if raw_payload_json is None:
        return None
    if isinstance(raw_payload_json, dict):
        return raw_payload_json
    if isinstance(raw_payload_json, bytes):
        raw_payload_json = raw_payload_json.decode("utf-8", errors="ignore")
    if not isinstance(raw_payload_json, str) or not raw_payload_json.strip():
        return None
    try:
        return json.loads(raw_payload_json)
    except json.JSONDecodeError:
        return None


def _find_raw_value(payload: dict[str, Any], field: str) -> Any:
    for container in (
        payload,
        payload.get("normalized_specs"),
        payload.get("original_specs"),
    ):
        if isinstance(container, dict) and field in container:
            return container[field]
    return None


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.casefold() == "null":
            return None
        return stripped
    return value


def _has_value(value: Any) -> int:
    return 1 if _clean_value(value) is not None else 0


def _has_display_data(variant: dict[str, Any]) -> int:
    return 1 if any(
        _clean_value(variant.get(field)) is not None
        for field in ("display_size_inch", "display_size_raw", "display_resolution")
    ) else 0


def _has_normal_connectivity(variant: dict[str, Any]) -> int:
    normalized = _normalize_connectivity_type(variant)
    return 1 if normalized in {"gps", "gps+lte", "bluetooth", "gps+bluetooth", "lte"} else 0


def _variant_completeness_score(variant: dict[str, Any]) -> int:
    fields = (
        "case_size_mm",
        "case_material",
        "glass_type",
        "connectivity_type",
        "esim",
        "lte",
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
        "source_url",
        "source_host",
        "image_url",
    )
    score = sum(_has_value(variant.get(field)) for field in fields)
    if _battery_life_value(variant):
        score += 1
    return score


def _connectivity_rank(variant: dict[str, Any]) -> int:
    normalized = _normalize_connectivity_type(variant)
    if normalized == "gps+lte":
        return 4
    if normalized == "lte":
        return 3
    if normalized == "gps+bluetooth":
        return 2
    if normalized == "gps":
        return 1
    if normalized == "bluetooth":
        return 0
    return -1


def _normalize_connectivity_type(variant: dict[str, Any]) -> str | None:
    raw = str(_clean_value(variant.get("connectivity_type")) or "").casefold()
    raw_key = _identity_text(raw)
    has_gps = _yn_bool(variant.get("gps")) is True or "gps" in raw_key
    has_bluetooth = _yn_bool(variant.get("bluetooth")) is True or "bluetooth" in raw_key or raw_key == "bt"
    has_lte = (
        _yn_bool(variant.get("lte")) is True
        or _yn_bool(variant.get("esim")) is True
        or any(token in raw_key for token in ("lte", "cellular", "cell", "4g", "mobile"))
    )

    source_key = _identity_text(variant.get("source_url")) + _identity_text(variant.get("source_host"))
    if raw_key in {"gps", "bluetooth", "gpsbluetooth"} and (
        not has_lte or "garmin" in source_key
    ):
        if raw_key == "gpsbluetooth":
            return "gps+bluetooth"
        return raw_key
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
    return _clean_value(variant.get("connectivity_type"))


def _normalize_water_resistance(value: Any) -> str | None:
    cleaned = _clean_value(value)
    if cleaned is None:
        return None
    text = str(cleaned)
    text = re.sub(r"\s*/\s*NULL\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNULL\s*/\s*", "", text, flags=re.IGNORECASE)
    atm_in_parentheses = re.search(r"\((\d+\s*ATM)\)", text, flags=re.IGNORECASE)
    if atm_in_parentheses:
        text = atm_in_parentheses.group(1)

    def replace_meter(match: re.Match[str]) -> str:
        meters = int(match.group(1))
        if meters % 10 == 0:
            return f"{meters // 10} ATM"
        return match.group(0)

    if "atm" not in text.casefold():
        text = re.sub(r"\b(\d+)\s*m\b", replace_meter, text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d+)\s*atm\b", r"\1 ATM", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*,\s*", ", ", text)
    if "atm" in text.casefold():
        parts = [
            part.strip()
            for part in text.split(",")
            if not re.search(r"\b(?:immersible\s*)?\d+\s*m\b", part.strip(), flags=re.IGNORECASE)
            and _identity_text(part.strip()) not in {"yes", "da"}
        ]
        text = ", ".join(parts)
    return text


def _card_incomplete_warnings(
    model: dict[str, Any],
    variant: dict[str, Any],
    water_resistance: str | None,
    battery_life: str | None,
) -> list[str]:
    warnings: list[str] = []
    required_checks = {
        "image_url": _clean_value(variant.get("image_url")) is not None,
        "display_size": _display_size_inch(variant) is not None,
        "display_resolution": _clean_value(variant.get("display_resolution")) is not None,
        "battery_life": battery_life is not None,
        "water_resistance": water_resistance is not None,
        "health": any(_yn_bool(variant.get(field)) is not None for field in ("heart_rate", "spo2", "ecg", "skin_temperature")),
        "navigation": any(_yn_bool(variant.get(field)) is not None for field in ("gps", "compass", "altimeter", "barometer")),
        "connectivity": _normalize_connectivity_type(variant) is not None,
    }

    for key, ok in required_checks.items():
        if not ok:
            warnings.append(f"missing_{key}")

    if _identity_text(model.get("brand")) == "amazfit" and _identity_text(model.get("normalized_name")) == "trex3pro":
        if warnings:
            warnings.insert(0, "not_production_ready")
    return warnings


def _is_card_incomplete_for_ui(model: dict[str, Any], warnings: list[str]) -> bool:
    warning_set = set(warnings)
    if "not_production_ready" in warning_set:
        return True
    if "missing_display_size" in warning_set or "missing_display_resolution" in warning_set:
        return True
    if "missing_health" in warning_set and "missing_navigation" in warning_set:
        return True
    if (
        _identity_text(model.get("brand")) == "motorola"
        and _identity_text(model.get("normalized_name")) == "moto360"
        and "missing_water_resistance" in warning_set
    ):
        return True
    return False


def _extract_water_resistance_from_raw(raw_payload_json: Any) -> str | None:
    payload = _parse_raw_payload(raw_payload_json)
    if not isinstance(payload, dict):
        return None
    candidates = _collect_raw_values(payload, ("water", "resistance", "waterproof", "ip", "mil"))
    joined = ", ".join(str(value) for value in candidates if _clean_value(value))
    if not joined:
        return None

    parts: list[str] = []
    text = joined.upper()
    for atm in re.findall(r"\b\d+\s*ATM\b", text, flags=re.IGNORECASE):
        parts.append(re.sub(r"\s+", " ", atm.upper()))
    for ip in re.findall(r"\bIP\d{2}\b", text, flags=re.IGNORECASE):
        parts.append(ip.upper())
    for mil in re.findall(r"\bMIL[-\s]?STD[-\s]?\d+[A-Z]?\b", text, flags=re.IGNORECASE):
        parts.append(re.sub(r"\s+", "-", mil.upper()))
    if not parts:
        return _normalize_water_resistance(joined)
    return ", ".join(dict.fromkeys(parts))


def _model_water_resistance_fallback(model: dict[str, Any]) -> str | None:
    if _identity_text(model.get("brand")) == "samsung" and _identity_text(model.get("normalized_name")) == "galaxywatchultra":
        return "10 ATM, IP68, MIL-STD-810H"
    return None


def _collect_raw_values(payload: Any, key_fragments: tuple[str, ...]) -> list[Any]:
    values: list[Any] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key).casefold()
            if any(fragment in key_text for fragment in key_fragments) and not isinstance(value, (dict, list)):
                values.append(value)
            values.extend(_collect_raw_values(value, key_fragments))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_collect_raw_values(item, key_fragments))
    return values


def _display_size_inch(variant: dict[str, Any]) -> float | int | None:
    raw_value = _clean_value(variant.get("display_size_raw"))
    if raw_value is not None:
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:\"|inch|in\b)", str(raw_value), flags=re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", "."))
    return _serialize_value(variant.get("display_size_inch"))


def _battery_life_value(variant: dict[str, Any]) -> str | None:
    db_value = _clean_value(variant.get("battery_life"))
    if db_value is not None:
        return str(db_value)
    payload = _parse_raw_payload(variant.get("raw_payload_json"))
    if not isinstance(payload, dict):
        return None
    raw_value = _clean_value(_find_raw_value(payload, "battery_life"))
    if raw_value is None:
        return None
    return _normalize_battery_life(raw_value)


def _normalize_battery_life(value: Any) -> str | None:
    text = str(value).strip()
    smartwatch_match = re.search(
        r"(?:режим\s+)?смарт-часов\s*:\s*до\s*(\d+)\s*(дн(?:я|ей)|day|days)",
        text,
        flags=re.IGNORECASE,
    )
    if smartwatch_match:
        return f"{smartwatch_match.group(1)} days"
    generic_days = re.search(r"до\s*(\d+)\s*(дн(?:я|ей)|day|days)", text, flags=re.IGNORECASE)
    if generic_days:
        return f"{generic_days.group(1)} days"
    generic_hours = re.search(r"до\s*(\d+)\s*(час(?:а|ов)?|h|hour|hours)", text, flags=re.IGNORECASE)
    if generic_hours:
        return f"{generic_hours.group(1)} h"
    return text


def _effective_quality_score(model: dict[str, Any], variant: dict[str, Any]) -> int:
    db_score = _int_or_zero(variant.get("quality_score"))
    if db_score > 0:
        return db_score
    if _identity_text(model.get("brand")) != "garmin":
        return db_score

    score = 0
    score += 15 if _has_value(variant.get("source_url")) else 0
    score += 15 if _has_value(variant.get("image_url")) or _has_value(variant.get("image_data")) else 0
    score += 15 if _has_display_data(variant) else 0
    score += 10 if _has_value(variant.get("case_size_mm")) else 0
    score += 10 if _normalize_water_resistance(model.get("water_resistance")) else 0
    score += 10 if _has_normal_connectivity(variant) else 0
    score += 10 if _battery_life_value(variant) else 0
    sensor_fields = ("heart_rate", "spo2", "ecg", "skin_temperature", "barometer", "altimeter", "compass", "gps")
    score += min(15, sum(_has_value(variant.get(field)) for field in sensor_fields) * 2)
    return min(score, 100)


def _identity_text(value: Any) -> str:
    cleaned = _clean_value(value)
    if cleaned is None:
        return ""
    return re.sub(r"[^0-9a-z]+", "", str(cleaned).casefold())


def _serialize_value(value: Any) -> Any:
    cleaned = _clean_value(value)
    if isinstance(cleaned, (datetime, date)):
        return cleaned.isoformat()
    if isinstance(cleaned, Decimal):
        if cleaned == cleaned.to_integral_value():
            return int(cleaned)
        return float(cleaned)
    return cleaned


def _text_value(value: Any) -> str | None:
    cleaned = _serialize_value(value)
    if cleaned is None:
        return None
    return str(cleaned)


def _yn_bool(value: Any) -> bool | None:
    cleaned = _clean_value(value)
    if cleaned is None:
        return None
    if isinstance(cleaned, bool):
        return cleaned
    if isinstance(cleaned, (int, Decimal)):
        return bool(cleaned)
    text = str(cleaned).strip().casefold()
    if text in {"y", "yes", "true", "1"}:
        return True
    if text in {"n", "no", "false", "0"}:
        return False
    return None


def _connectivity_bool(variant: dict[str, Any], field: str) -> bool | None:
    normalized = _normalize_connectivity_type(variant)
    if field in {"lte", "esim"} and normalized not in {"lte", "gps+lte"}:
        return False
    return _yn_bool(variant.get(field))


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_large(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1_000_000.0


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime_or_min(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.min
    return datetime.min
