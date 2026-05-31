# Watch Card API

A small API service for smartwatch product cards with read-only database access.

The project turns smartwatch data from MySQL into clean, frontend-ready JSON. It
is designed for product pages, comparison pages, autocomplete, and internal data
quality checks.

The service does not parse external websites, does not write to the database, and
does not expose binary image data in API responses.

## What It Does

- Reads smartwatch models from `g_watch_model`
- Reads concrete watch variants from `g_watch_variant`
- Builds one normalized card response per watch model
- Selects the best `main_variant` from available variants
- Deduplicates old or technical duplicate variants
- Normalizes common fields such as connectivity, water resistance, booleans, and display names
- Marks incomplete cards with `incomplete=true` and readable warnings
- Serves a simple demo UI for checking cards by free-form search

## Data Model

The API expects an existing MySQL database with two main tables:

- `g_watch_model` contains the base watch model, for example `Apple Watch Series 9`
- `g_watch_variant` contains concrete card data and variant-specific specs, for example `41mm GPS`

Every model should have at least one usable variant. If a model has no explicit
variant, the expected canonical variant is:

```text
variant_name = NULL
is_canonical = 1
```

The API treats the model as the product family and the variant as the concrete
configuration used to build the card.

## API Behavior

The service prepares card data for direct frontend usage:

- `title` is built from brand and model name without duplicate brand text
- `display_name` removes duplicated model text from variant names
- only one variant is returned as canonical in the API response
- weak variants, parser stubs, and lower-quality technical duplicates are hidden
- `image_data` is never returned in JSON, only `has_image_data`
- cards prefer local static image files generated from `image_data` for every source
- external `image_url` values are used only when no database image data is available
- `raw_payload_json` is not exposed as-is
- selected useful raw fields are exposed through `raw_extra`
- `Y` / `N` database values are converted to booleans in card blocks
- incomplete cards are still returned when useful data exists

Useful extra fields may include:

- `battery_life_gps`
- `battery_life_training`
- `launch_price`
- `sleep_tracking`
- `sport_modes`
- `vo2_max`
- `glonass`
- `galileo`
- `beidou`
- `solar_charging`
- `ant_plus`
- `android_compatible`
- `ios_compatible`

## Main Variant Selection

The main variant is selected by practical card quality, not only by the raw
database flag.

The service prefers variants with:

- source URL
- image URL
- display data
- battery data
- water resistance
- case size
- normal connectivity
- higher completeness
- higher quality score
- fresher update time

If several variants are marked canonical in the database, the API still exposes
only one canonical variant in the response.

## Variant Cleanup

The response hides variants that are not useful for the website, including:

- `quality_score = 0`
- parser stubs such as `gsmarena_stub`
- variants without useful differences from the main variant
- variants with no case size when better sized variants exist
- old duplicates with the same business key
- variant names that repeat the model name, for example `Active 2 Active 2`

Duplicate variants are compared by fields such as:

- case size
- case material
- glass type
- connectivity type
- LTE / eSIM flags
- completeness
- quality score

## Connectivity Normalization

Connectivity values are normalized into a small set of frontend-friendly values:

- `gps`
- `gps+lte`
- `gps+bluetooth`
- `bluetooth`
- `lte`

The original boolean capabilities are still available in the `connectivity`
block.

## Water Resistance Normalization

The API normalizes common water resistance formats where possible:

- `50m` becomes `5 ATM`
- `100m` becomes `10 ATM`
- `Да (5 ATM)` becomes `5 ATM`
- `10 ATM / NULL` becomes `10 ATM`

If a reliable value is missing, the card may be returned with an incomplete
warning instead of showing a fake value.

## Endpoints

### Health Check

```http
GET /health
```

### Get Card by Model ID

```http
GET /api/watch-card/{model_id}
```

Example:

```bash
curl "http://127.0.0.1:8000/api/watch-card/123"
```

### Get Card by Brand and Normalized Name

```http
GET /api/watch-card/by-name?brand=Garmin&normalized_name=fenix%207
```

Example:

```bash
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Garmin&normalized_name=fenix%207"
```

### Search Cards

```http
GET /api/watch-card/search?q=fenix&brand=Garmin&limit=20
```

Example:

```bash
curl "http://127.0.0.1:8000/api/watch-card/search?q=fenix&limit=5"
```

Search is useful for autocomplete, manual checks, and suggestions when an exact
card lookup fails.

## Response Example

```json
{
  "model": {
    "id": 123,
    "brand": "Garmin",
    "model_name": "Fenix 7",
    "normalized_name": "fenix 7",
    "announce_date": "2022-01-18",
    "os": "Garmin OS",
    "cpu": null,
    "gpu": null,
    "ram": null,
    "storage": null
  },
  "title": "Garmin Fenix 7",
  "image": {
    "url": "/watch-images/variant-456.jpg",
    "has_image_data": true
  },
  "display": {
    "type": "AMOLED",
    "size_inch": 1.3,
    "size_raw": "1.3\"",
    "resolution": "260x260"
  },
  "materials": {
    "case_material": "stainless_steel",
    "glass_type": "Sapphire"
  },
  "battery": {
    "capacity_mah": null,
    "life": "22 days"
  },
  "protection": {
    "water_resistance": "10 ATM"
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
    "source_url": "https://example.com/source",
    "source_host": "example.com"
  },
  "variants": [
    {
      "id": 456,
      "variant_name": null,
      "display_name": "Garmin Fenix 7",
      "case_size_mm": 47,
      "case_material": "stainless_steel",
      "glass_type": "Sapphire",
      "connectivity_type": "gps+bluetooth",
      "battery_life": "22 days",
      "quality_score": 100,
      "is_canonical": true
    }
  ],
  "source": {
    "host": "example.com",
    "url": "https://example.com/source"
  },
  "raw_extra": {
    "battery_life_gps": "289 h",
    "solar_charging": "Y"
  },
  "incomplete": false,
  "warnings": []
}
```

## Demo UI

The project includes a lightweight static frontend served by FastAPI:

```text
http://127.0.0.1:8000/
```

The demo UI allows free-form search, for example:

- `Apple Watch Series 9`
- `apple watch ultra 2`
- `Applt watch ultra`
- `Samsung Galaxy Watch7`
- `Garmin Fenix 7 Pro`
- `Garmin Forerunner 165`
- `Huawei Watch GT 4`
- `Amazfit GTR 4`
- `Xiaomi Watch 2 Pro`
- `Google Pixel Watch 2`
- `OnePlus Watch 2`
- `Motorola Moto 360`

The frontend normalizes user input, detects known brands, tries tolerant model
matching, and shows suggestions when an exact card is not found.

Enable `Debug` in the UI to view:

- source host
- source URL
- quality score
- incomplete status
- warnings
- raw response JSON

## Requirements

- Python 3.10 or newer
- MySQL with populated watch tables
- Direct MySQL access or optional SSH tunnel access

Python dependencies are listed in `requirements.txt`.

## Configuration

Create a local environment file:

```bash
copy .env.example .env
```

On macOS or Linux:

```bash
cp .env.example .env
```

Fill in the MySQL connection:

```env
SQL_HOSTNAME=localhost
SQL_PORT=3306
SQL_USERNAME=
SQL_PASSWORD=
SQL_DATABASE=
```

Optional SSH tunnel settings:

```env
SSH_HOST=
SSH_PORT=22
SSH_USER=
SSH_PASSWORD=
```

Leave SSH fields empty when MySQL is available directly.

## Installation

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m uvicorn watch_api.app:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

## Checks

Run unit tests:

```bash
python -m pytest
```

Run smoke checks after starting the server:

```bash
python scripts/smoke_check_api.py
```

Manual API checks:

```bash
curl "http://127.0.0.1:8000/health"
curl "http://127.0.0.1:8000/api/watch-card/search?q=fenix&limit=5"
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Garmin&normalized_name=forerunner%20165"
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Samsung&normalized_name=galaxy%20watch7"
curl "http://127.0.0.1:8000/api/watch-card/by-name?brand=Apple&normalized_name=watch%20series%209"
```

## Local Images

External watch image URLs can be unstable, so watch images are stored as local
static files when `image_data` is available.

Export existing database images:

```bash
python scripts/export_watch_images.py
```

Generated files are written to:

```text
watch_api/static/watch-images/
```

The generated image files are runtime data and are ignored by Git.

## Project Structure

```text
watch_api/
  app.py
  config.py
  db.py
  routes/
    watch_card_routes.py
  schemas/
    watch_card_schema.py
  services/
    watch_card_service.py
  static/
    watch-images/
    index.html
    styles.css
    app.js
scripts/
  export_watch_images.py
  smoke_check_api.py
tests/
  test_watch_card_service.py
```

## Repository Notes

Local secrets and generated files should not be committed.

The repository includes `.env.example` for configuration shape, while `.env` is
ignored by Git.

The API is intentionally small and keeps database access read-only. Parser logic,
database imports, and frontend production application code should stay outside
this service unless the project is intentionally expanded later.
