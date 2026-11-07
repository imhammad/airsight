"""Response shapes of the public API (ADR 0008). Field names here are a promise to clients."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Health = Literal["ok", "excluded"]


class Reading(BaseModel):
    pm25_corrected: float = Field(description="Corrected PM2.5 in µg/m³, one decimal")
    pm25_raw: float | None = Field(description="The sensor's own PM2.5 in µg/m³, one decimal")
    aqi_category: str = Field(description="US EPA category of pm25_corrected (2024 breakpoints)")
    model_version: str = Field(description="The model that produced pm25_corrected")
    observed_at: datetime = Field(description="Start of the hour, UTC")
    stale: bool = Field(description="True when the reading is more than 6 hours old")


class Sensor(BaseModel):
    id: str = Field(description="Stable id, such as pa-131075 for PurpleAir sensor 131075")
    name: str | None
    latitude: float
    longitude: float
    health: Health = Field(description="excluded when quality checks found the sensor unreliable")


class SensorDetail(Sensor):
    latest_reading: Reading | None = Field(description="null for excluded sensors")


class NearbyReading(BaseModel):
    sensor: Sensor
    distance_km: float
    reading: Reading


class SensorPage(BaseModel):
    data: list[Sensor]
    next_cursor: str | None = Field(description="Pass back as cursor for the next page")


class NearbyPage(BaseModel):
    data: list[NearbyReading]
    next_cursor: str | None
