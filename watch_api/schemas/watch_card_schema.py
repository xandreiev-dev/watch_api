from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# Pydantic schemas document the public API shape and catch accidental type drift.
class WatchModelSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    brand: str | None = None
    model_name: str | None = None
    normalized_name: str | None = None
    announce_date: str | None = None
    os: str | None = None
    cpu: str | None = None
    gpu: str | None = None
    ram: str | None = None
    storage: str | None = None


class WatchImageSchema(BaseModel):
    url: str | None = None
    has_image_data: bool


class WatchDisplaySchema(BaseModel):
    type: str | None = None
    size_inch: float | None = None
    size_raw: str | None = None
    resolution: str | None = None


class WatchMaterialsSchema(BaseModel):
    case_material: str | None = None
    glass_type: str | None = None


class WatchBatterySchema(BaseModel):
    capacity_mah: int | None = None
    life: str | None = None


class WatchProtectionSchema(BaseModel):
    water_resistance: str | None = None


class WatchNavigationSchema(BaseModel):
    gps: bool | None = None
    compass: bool | None = None
    altimeter: bool | None = None
    barometer: bool | None = None


class WatchHealthSchema(BaseModel):
    heart_rate: bool | None = None
    spo2: bool | None = None
    ecg: bool | None = None
    skin_temperature: bool | None = None


class WatchConnectivitySchema(BaseModel):
    type: str | None = None
    connectivity_type: str | None = None
    bluetooth: bool | None = None
    wifi: bool | None = None
    nfc: bool | None = None
    lte: bool | None = None
    esim: bool | None = None


class MainVariantSchema(BaseModel):
    id: int
    variant_name: str | None = None
    display_name: str
    case_size_mm: float | None = None
    quality_score: int | None = None
    is_canonical: bool | None = None
    source_url: str | None = None
    source_host: str | None = None


class VariantSummarySchema(BaseModel):
    id: int
    variant_name: str | None = None
    display_name: str
    case_size_mm: float | None = None
    case_material: str | None = None
    glass_type: str | None = None
    connectivity_type: str | None = None
    battery_life: str | None = None
    quality_score: int | None = None
    is_canonical: bool | None = None


class WatchSourceSchema(BaseModel):
    host: str | None = None
    url: str | None = None


class WatchCardSchema(BaseModel):
    # Main card response. Blocks are always present so the frontend can render safely.
    model: WatchModelSchema
    title: str
    image: WatchImageSchema
    display: WatchDisplaySchema
    materials: WatchMaterialsSchema
    battery: WatchBatterySchema
    protection: WatchProtectionSchema
    navigation: WatchNavigationSchema
    health: WatchHealthSchema
    connectivity: WatchConnectivitySchema
    main_variant: MainVariantSchema
    variants: list[VariantSummarySchema]
    source: WatchSourceSchema
    raw_extra: dict[str, Any]
    incomplete: bool = False
    warnings: list[str] = Field(default_factory=list)


class WatchSearchItemSchema(BaseModel):
    # Compact search result used before a full card is loaded.
    id: int
    brand: str | None = None
    model_name: str | None = None
    normalized_name: str | None = None
    image_url: str | None = None
    battery_life: str | None = None
    display_resolution: str | None = None
    water_resistance: str | None = None
