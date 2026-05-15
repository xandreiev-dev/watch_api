# Watch Card API

Mini backend service for smartwatch cards. The service reads existing MySQL tables
`g_watch_model` and `g_watch_variant` and returns frontend-ready JSON.

This service does not parse pages, does not write to the database, and does not
return `image_data`.

## Setup

Use Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill `.env`:

```env
SQL_HOSTNAME=localhost
SQL_PORT=3306
SQL_USERNAME=
SQL_PASSWORD=
SQL_DATABASE=
```

If MySQL is available only through SSH, add:

```env
SSH_HOST=
SSH_PORT=22
SSH_USER=
SSH_PASSWORD=
```

## Run

From this project directory:

```bash
python -m uvicorn watch_api.app:app --reload --host 127.0.0.1 --port 8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

Demo frontend:

```text
http://127.0.0.1:8000/
```

Health check:

```text
http://127.0.0.1:8000/health
```

## Endpoints

### Get card by model id

```bash
curl "http://127.0.0.1:8000/api/watch-card/123"
```

### Get card by brand and normalized name

```bash
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Garmin&normalized_name=fenix%207"
```

### Search cards

```bash
curl "http://127.0.0.1:8000/api/watch-card/search?q=fenix&limit=5"
curl "http://127.0.0.1:8000/api/watch-card/search?q=watch&brand=Samsung&limit=20"
```

## Response Shape

Card endpoints return:

```json
{
  "model": {
    "id": 123,
    "brand": "Garmin",
    "model_name": "Fenix 7",
    "normalized_name": "fenix 7",
    "announce_date": "2022-01-18",
    "os": null,
    "cpu": null,
    "gpu": null,
    "ram": null,
    "storage": null
  },
  "title": "Garmin Fenix 7",
  "image": {
    "url": "https://nanoreview.pro/example.png",
    "has_image_data": true
  },
  "display": {
    "type": "lcd",
    "size_inch": 1.3,
    "size_raw": "1.3\" (33mm)",
    "resolution": "260x260"
  },
  "materials": {
    "case_material": null,
    "glass_type": "Sapphire"
  },
  "battery": {
    "capacity_mah": null,
    "life": "22 days"
  },
  "protection": {
    "water_resistance": "100m, 10ATM"
  },
  "navigation": {
    "gps": true,
    "compass": true,
    "altimeter": true,
    "barometer": true
  },
  "health": {
    "heart_rate": true,
    "spo2": true,
    "ecg": false,
    "skin_temperature": true
  },
  "connectivity": {
    "type": "gps+bluetooth",
    "connectivity_type": "gps+bluetooth",
    "bluetooth": true,
    "wifi": true,
    "nfc": true,
    "lte": false,
    "esim": false
  },
  "main_variant": {
    "id": 456,
    "variant_name": null,
    "display_name": "Garmin Fenix 7",
    "case_size_mm": 47,
    "quality_score": 100,
    "is_canonical": true,
    "source_url": "https://nanoreview.pro/example",
    "source_host": "nanoreview.pro"
  },
  "variants": [
    {
      "id": 456,
      "variant_name": null,
      "display_name": "Garmin Fenix 7",
      "case_size_mm": 47,
      "case_material": null,
      "glass_type": "Sapphire",
      "connectivity_type": "gps+bluetooth",
      "battery_life": "22 days",
      "quality_score": 100,
      "is_canonical": true
    }
  ],
  "source": {
    "host": "nanoreview.pro",
    "url": "https://nanoreview.pro/example"
  },
  "raw_extra": {
    "battery_life_gps": "289 h",
    "solar_charging": "Y"
  }
}
```

Search returns a short list:

```json
[
  {
    "id": 123,
    "brand": "Garmin",
    "model_name": "Fenix 7",
    "normalized_name": "fenix 7",
    "image_url": "https://nanoreview.pro/example.png",
    "battery_life": "22 days",
    "display_resolution": "260x260",
    "water_resistance": "100m, 10ATM"
  }
]
```

## Main Variant Rule

The main variant is selected in this order:

1. `is_canonical = 1`
2. highest `quality_score`
3. freshest `updated_at`

If there is no canonical variant, the service uses the same quality and freshness
rules across all variants.

Variants in the response are sorted by:

1. `is_canonical DESC`
2. `quality_score DESC`
3. `case_size_mm ASC`
4. `variant_name ASC`
5. `id ASC`

## Local Checks

Run unit tests:

```bash
python -m pytest
```

Run HTTP smoke checks after starting the server:

```bash
python scripts/smoke_check_api.py
```

Manual API checks after starting the server:

```bash
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Garmin&normalized_name=fenix%207"
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Samsung&normalized_name=galaxy%20watch6"
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Apple&normalized_name=watch%20series%209"
```

Demo UI checks:

```text
Apple Watch Series 9
Applt watch ultra
samsung watch 7
Garmin Forerunner 165
Amazfit GTR 4
Xiaomi Watch 2 Pro
```

Enable `Debug` in the demo UI to show source, quality score, incomplete warnings,
and raw JSON.

Recommended models for smoke checks:

- Garmin Fenix 7
- Garmin Venu 2
- Samsung Galaxy Watch6
- Samsung Galaxy Watch7
- Apple Watch Series 9
- Huawei Watch GT 4
- Google Pixel Watch 3
- OnePlus Watch 3
- Motorola Moto Watch 120
