from datetime import datetime
from decimal import Decimal

import pytest
import watch_api.services.watch_card_service as watch_card_service
from watch_api.services.watch_card_service import (
    build_model_title,
    build_variant_display_name,
    build_watch_card,
    choose_main_variant,
    extract_raw_extra,
    prepare_response_variants,
)


# The tests use plain dictionaries that look like DB rows, so service logic can be checked without MySQL.
@pytest.fixture(autouse=True)
def isolated_image_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(watch_card_service, "IMAGE_STORAGE_DIR", tmp_path / "watch-images")


def test_choose_main_variant_prefers_complete_lte_variant_over_db_canonical_flag():
    variants = [
        {
            "id": 1,
            "is_canonical": 1,
            "quality_score": 100,
            "updated_at": datetime(2024, 1, 1),
            "gps": "Y",
            "lte": "N",
        },
        {
            "id": 2,
            "is_canonical": 0,
            "quality_score": 80,
            "updated_at": datetime(2024, 1, 2),
            "battery_life": "36 h",
            "gps": "Y",
            "lte": "Y",
            "image_url": "https://example.com/watch.png",
            "source_url": "https://example.com/watch",
        },
    ]

    assert choose_main_variant(variants)["id"] == 2


def test_title_does_not_duplicate_brand():
    assert build_model_title("Apple", "Apple Watch Series 9") == "Apple Watch Series 9"
    assert build_model_title("Garmin", "Fenix 7") == "Garmin Fenix 7"


def test_variant_display_name_hides_standard_default_base():
    model = {"brand": "Garmin", "model_name": "Fenix 7"}

    assert build_variant_display_name(model, None) == "Garmin Fenix 7"
    assert build_variant_display_name(model, "Standard") == "Garmin Fenix 7"
    assert build_variant_display_name(model, "Sapphire Solar") == "Garmin Fenix 7 Sapphire Solar"


def test_variant_display_name_strips_model_name_prefix():
    model = {"brand": "Apple", "model_name": "Watch Series 9", "normalized_name": "watch series 9"}

    assert build_variant_display_name(model, "Watch Series 9 41mm") == "Apple Watch Series 9 41mm"
    assert build_variant_display_name(model, "Apple Watch Series 9 Watch Series 9 41mm") == "Apple Watch Series 9 41mm"


def test_extract_raw_extra_only_allowed_fields():
    payload = {
        "parser_version": "1",
        "normalized_specs": {
            "battery_life_gps": "289 h",
            "solar_charging": "Y",
            "ignored": "secret",
        },
        "original_specs": {
            "galileo": "Y",
        },
    }

    assert extract_raw_extra(payload) == {
        "battery_life_gps": "289 h",
        "galileo": "Y",
        "solar_charging": "Y",
    }


def test_build_watch_card_shape_and_variant_sorting():
    # This is the broad shape test: it guards the public response contract.
    model = {
        "id": 123,
        "brand": "Garmin",
        "model_name": "Fenix 7",
        "normalized_name": "fenix 7",
        "announce_date": "2022-01-18",
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": "lcd",
        "water_resistance": "100m, 10ATM",
    }
    variants = [
        {
            "id": 457,
            "variant_name": "Sapphire Solar",
            "case_size_mm": 47,
            "case_material": None,
            "glass_type": "Sapphire",
            "connectivity_type": "gps+bluetooth",
            "display_size_inch": 1.3,
            "display_size_raw": '1.3" (33mm)',
            "display_resolution": "260x260",
            "battery_capacity_mah": None,
            "battery_life": "22 days",
            "heart_rate": "Y",
            "spo2": "Y",
            "ecg": "N",
            "skin_temperature": "Y",
            "barometer": "Y",
            "altimeter": "Y",
            "compass": "Y",
            "gps": "Y",
            "nfc": "Y",
            "wifi": "Y",
            "bluetooth": "Y",
            "lte": "N",
            "esim": "N",
            "quality_score": 100,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
            "source_url": "https://nanoreview.pro/watch",
            "source_host": "nanoreview.pro",
            "image_url": "https://nanoreview.pro/watch.png",
            "image_data": b"image",
            "raw_payload_json": '{"normalized_specs":{"solar_charging":"Y"}}',
        },
        {
            "id": 456,
            "variant_name": None,
            "case_size_mm": 47,
            "case_material": None,
            "glass_type": "Sapphire",
            "connectivity_type": "gps+bluetooth",
            "battery_life": "22 days",
            "quality_score": 90,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 2),
        },
    ]

    card = build_watch_card(model, variants)

    assert card["title"] == "Garmin Fenix 7"
    assert card["image"]["url"] == "/watch-images/variant-457.jpg"
    assert card["image"]["has_image_data"] is True
    assert (watch_card_service.IMAGE_STORAGE_DIR / "variant-457.jpg").read_bytes() == b"image"
    assert card["navigation"]["gps"] is True
    assert card["connectivity"]["wifi"] is True
    assert card["connectivity"]["lte"] is False
    assert card["connectivity"]["type"] == "gps+bluetooth"
    assert card["main_variant"]["id"] == 457
    assert card["main_variant"]["is_canonical"] is True
    assert card["variants"][0]["id"] == 457
    assert card["variants"][1]["id"] == 456
    assert card["variants"][1]["is_canonical"] is False
    assert card["raw_extra"] == {"solar_charging": "Y"}


def test_gsmarena_image_data_is_saved_locally():
    model = {
        "id": 125,
        "brand": "Test",
        "model_name": "Watch",
        "normalized_name": "watch",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": None,
        "water_resistance": None,
    }
    variants = [
        {
            "id": 2,
            "variant_name": None,
            "quality_score": 80,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
            "source_host": "gsmarena.com",
            "image_url": "https://fdn.gsmarena.com/imgroot/watch.jpg",
            "image_data": b"image",
        }
    ]

    card = build_watch_card(model, variants)

    assert card["image"]["url"] == "/watch-images/variant-2.jpg"
    assert card["image"]["has_image_data"] is True
    assert (watch_card_service.IMAGE_STORAGE_DIR / "variant-2.jpg").read_bytes() == b"image"


def test_existing_local_image_file_is_used_without_blob():
    model = {
        "id": 127,
        "brand": "Test",
        "model_name": "Watch",
        "normalized_name": "watch",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": None,
        "water_resistance": None,
    }
    watch_card_service.IMAGE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    (watch_card_service.IMAGE_STORAGE_DIR / "variant-4.png").write_bytes(b"png")
    variants = [
        {
            "id": 4,
            "variant_name": None,
            "quality_score": 80,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
            "source_host": "nanoreview.pro",
            "image_url": "https://nanoreview.pro/watch.jpg",
            "image_data_present": 1,
        }
    ]

    card = build_watch_card(model, variants)

    assert card["image"]["url"] == "/watch-images/variant-4.png"
    assert card["image"]["has_image_data"] is True


def test_image_data_present_can_be_loaded_lazily(monkeypatch):
    model = {
        "id": 128,
        "brand": "Garmin",
        "model_name": "Venu 3",
        "normalized_name": "venu 3",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": None,
        "water_resistance": None,
    }
    variants = [
        {
            "id": 5,
            "variant_name": None,
            "quality_score": 80,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
            "source_host": "garmin.ru",
            "image_url": "https://garmin.ru/watch.jpg",
            "image_data_present": 1,
        }
    ]
    monkeypatch.setattr(watch_card_service, "_fetch_variant_image_data", lambda variant_id: b"image")

    card = build_watch_card(model, variants)

    assert card["image"]["url"] == "/watch-images/variant-5.jpg"
    assert card["image"]["has_image_data"] is True
    assert (watch_card_service.IMAGE_STORAGE_DIR / "variant-5.jpg").read_bytes() == b"image"


def test_external_non_gsmarena_image_without_image_data_gets_warning():
    model = {
        "id": 126,
        "brand": "Test",
        "model_name": "Watch",
        "normalized_name": "watch",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": None,
        "water_resistance": None,
    }
    variants = [
        {
            "id": 3,
            "variant_name": None,
            "quality_score": 80,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
            "source_host": "example.com",
            "image_url": "https://example.com/watch.jpg",
        }
    ]

    card = build_watch_card(model, variants)

    assert card["image"]["url"] == "https://example.com/watch.jpg"
    assert card["image"]["has_image_data"] is False
    assert "missing_image_data" in card["warnings"]


def test_build_watch_card_serializes_numeric_model_memory_fields_as_text():
    model = {
        "id": 124,
        "brand": "Test",
        "model_name": "Galaxy Watch6",
        "normalized_name": "galaxy watch6",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": Decimal("2.0"),
        "storage": 16,
        "display_type": None,
        "water_resistance": None,
    }
    variants = [
        {
            "id": 1,
            "variant_name": None,
            "quality_score": 1,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
        }
    ]

    card = build_watch_card(model, variants)

    assert card["model"]["ram"] == "2"
    assert card["model"]["storage"] == "16"


def test_model_name_variant_is_hidden_and_duplicate_variant_is_collapsed():
    # Amazfit Active 2 exposed the classic duplicate-name problem: model name was stored as variant name.
    model = {
        "id": 300,
        "brand": "Amazfit",
        "model_name": "Active 2",
        "normalized_name": "active 2",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": "AMOLED",
        "water_resistance": "5 ATM",
    }
    variants = [
        {
            "id": 301,
            "variant_name": "Active 2",
            "case_size_mm": 44,
            "case_size_mm_key": "44",
            "connectivity_type": "bluetooth",
            "connectivity_key": "bluetooth",
            "esim": "N",
            "esim_key": "0",
            "lte": "N",
            "lte_key": "0",
            "quality_score": 20,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
        },
        {
            "id": 880,
            "variant_name": None,
            "case_size_mm": 44,
            "case_size_mm_key": "44",
            "connectivity_type": "bluetooth",
            "connectivity_key": "bluetooth",
            "esim": "N",
            "esim_key": "0",
            "lte": "N",
            "lte_key": "0",
            "quality_score": 70,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 2),
            "battery_life": "10 days",
            "bluetooth": "Y",
            "wifi": "N",
            "nfc": "N",
        },
    ]

    response_variants = prepare_response_variants(model, variants)
    card = build_watch_card(model, variants)

    assert [variant["id"] for variant in response_variants] == [880]
    assert card["main_variant"]["id"] == 880
    assert card["main_variant"]["variant_name"] is None
    assert card["main_variant"]["display_name"] == "Amazfit Active 2"
    assert card["variants"] == [
        {
            "id": 880,
            "variant_name": None,
            "display_name": "Amazfit Active 2",
            "case_size_mm": 44,
            "case_material": None,
            "glass_type": None,
            "connectivity_type": "bluetooth",
            "battery_life": "10 days",
            "quality_score": 70,
            "is_canonical": True,
        }
    ]
    assert card["connectivity"]["bluetooth"] is True
    assert card["connectivity"]["wifi"] is False
    assert card["connectivity"]["nfc"] is False


def test_only_main_variant_is_canonical_and_connectivity_is_normalized():
    # The API response must expose only one canonical variant even if the DB has several.
    model = {
        "id": 400,
        "brand": "Apple",
        "model_name": "Watch Ultra 2",
        "normalized_name": "watch ultra 2",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": None,
        "water_resistance": "50m, IP68",
    }
    variants = [
        {
            "id": 10,
            "variant_name": "49mm GPS",
            "case_size_mm": 49,
            "connectivity_type": "gps",
            "gps": "Y",
            "lte": "N",
            "esim": "N",
            "quality_score": 100,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
        },
        {
            "id": 11,
            "variant_name": "49mm LTE",
            "case_size_mm": 49,
            "connectivity_type": "gps_cellular",
            "gps": "Y",
            "lte": "Y",
            "esim": "Y",
            "battery_life": "36 h",
            "image_url": "https://example.com/ultra.png",
            "source_url": "https://example.com/ultra",
            "quality_score": 90,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
        },
    ]

    card = build_watch_card(model, variants)

    assert card["protection"]["water_resistance"] == "5 ATM, IP68"
    assert card["main_variant"]["id"] == 11
    assert card["main_variant"]["is_canonical"] is True
    assert card["connectivity"]["type"] == "gps+lte"
    assert card["variants"][0]["id"] == 11
    assert card["variants"][0]["is_canonical"] is True
    assert card["variants"][0]["connectivity_type"] == "gps+lte"
    assert card["variants"][1]["id"] == 10
    assert card["variants"][1]["is_canonical"] is False
    assert card["variants"][1]["connectivity_type"] == "gps"


def test_samsung_junk_variants_are_filtered_and_display_raw_wins():
    # Samsung rows are noisy, so this keeps size guards, stub filtering, and display parsing covered.
    model = {
        "id": 297,
        "brand": "Samsung",
        "model_name": "Galaxy Watch7",
        "normalized_name": "galaxy watch7",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": "Super AMOLED",
        "water_resistance": "IP68, 50m",
    }
    variants = [
        {
            "id": 179,
            "variant_name": "44mm",
            "case_size_mm": 44,
            "display_size_inch": 1,
            "display_size_raw": '1.5"',
            "display_resolution": "480x480",
            "connectivity_type": "gps_cellular",
            "gps": "Y",
            "lte": "Y",
            "esim": "Y",
            "source_url": "https://example.com/watch7",
            "image_url": "https://example.com/watch7.png",
            "quality_score": 69,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
        },
        {
            "id": 613,
            "variant_name": "47mm",
            "case_size_mm": 47,
            "quality_score": 100,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 2),
        },
        {
            "id": 536,
            "variant_name": None,
            "connectivity_type": "gsmarena_stub",
            "quality_score": 0,
            "is_canonical": 0,
            "updated_at": datetime(2024, 1, 3),
        },
        {
            "id": 358,
            "variant_name": None,
            "connectivity_type": "gps",
            "quality_score": 29,
            "is_canonical": 0,
            "updated_at": datetime(2024, 1, 4),
        },
    ]

    card = build_watch_card(model, variants)

    assert card["display"]["size_inch"] == 1.5
    assert card["protection"]["water_resistance"] == "IP68, 5 ATM"
    assert [variant["id"] for variant in card["variants"]] == [179]
    assert card["variants"][0]["connectivity_type"] == "gps+lte"


def test_non_samsung_zero_quality_canonical_placeholder_is_usable():
    # Some older imports only have a minimal canonical row; that should still render a basic card.
    model = {
        "id": 99,
        "brand": "Garmin",
        "model_name": "forerunner 265",
        "normalized_name": "forerunner 265",
        "announce_date": "2023-03-01",
        "os": "Garmin OS",
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": None,
        "water_resistance": None,
    }
    variants = [
        {
            "id": 390,
            "variant_name": "forerunner 265",
            "case_size_mm": None,
            "connectivity_type": "gps",
            "quality_score": 0,
            "is_canonical": 1,
            "updated_at": datetime(2024, 1, 1),
        }
    ]

    card = build_watch_card(model, variants)

    assert card["main_variant"]["id"] == 390
    assert card["main_variant"]["variant_name"] is None
    assert card["main_variant"]["is_canonical"] is True
    assert card["variants"][0]["display_name"] == "Garmin forerunner 265"
    assert card["connectivity"]["type"] == "gps"


def test_garmin_ru_zero_db_score_gets_effective_quality_and_battery_from_raw():
    # Garmin.ru can provide usable specs while quality_score is still zero in the database.
    model = {
        "id": 89,
        "brand": "Garmin",
        "model_name": "Forerunner 165",
        "normalized_name": "forerunner 165",
        "announce_date": None,
        "os": None,
        "cpu": None,
        "gpu": None,
        "ram": None,
        "storage": None,
        "display_type": "AMOLED",
        "water_resistance": "Да (5 ATM)",
    }
    variants = [
        {
            "id": 29,
            "variant_name": "forerunner 165",
            "case_size_mm": 43,
            "connectivity_type": "gps",
            "display_size_inch": "1.20",
            "display_size_raw": '1.2" (30.4mm)',
            "display_resolution": "390x390",
            "heart_rate": "Y",
            "spo2": "Y",
            "ecg": "N",
            "skin_temperature": "N",
            "barometer": "Y",
            "altimeter": "Y",
            "compass": "Y",
            "gps": "Y",
            "bluetooth": "Y",
            "wifi": "N",
            "nfc": "N",
            "quality_score": 0,
            "is_canonical": 1,
            "source_url": "https://www.garmin.ru/watches/catalog/forerunner/forerunner-165-black-slate-gray/#parameters",
            "source_host": "www.garmin.ru",
            "image_url": "https://www.garmin.ru/watch.png",
            "raw_payload_json": (
                '{"battery_life":"Режим смарт-часов: до 11 дней '
                'Экономичный режим смарт-часов: до 20 дней Режим GPS: до 19 часов"}'
            ),
            "updated_at": datetime(2024, 1, 1),
        }
    ]

    card = build_watch_card(model, variants)

    assert card["battery"]["life"] == "11 days"
    assert card["protection"]["water_resistance"] == "5 ATM"
    assert card["main_variant"]["quality_score"] > 0
    assert card["variants"][0]["battery_life"] == "11 days"
    assert card["variants"][0]["quality_score"] == card["main_variant"]["quality_score"]
