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


class ReadingPage(BaseModel):
    data: list[Reading]
    next_cursor: str | None


class FinalTest(BaseModel):
    """The release gate from ADR 0007: mean of per-station MAE on the 14-day final test."""

    headline_mae: float
    raw_headline_mae: float
    epa_headline_mae: float
    hours: int


class ModelInfo(BaseModel):
    name: str
    version: int
    model_version: str = Field(description="As it appears on every reading")
    dataset: str | None = Field(description="Content hash of the training dataset")
    trained_before: datetime | None = Field(description="The model never saw hours from here on")
    promoted_at: datetime
    final_test: FinalTest | None
    model_card: str


class Errors(BaseModel):
    """Mean absolute error against the official monitor, in µg/m³."""

    corrected: float | None
    raw: float | None
    epa: float | None = Field(description="The EPA's US-wide PurpleAir correction")


class StationAccuracy(BaseModel):
    station: str
    sensors: int
    hours: int
    mae: Errors
    bias: float | None = Field(description="Mean of corrected minus official; positive reads high")


class Accuracy(BaseModel):
    model_version: str
    start: datetime = Field(description="Never before the model's trained_before")
    end: datetime
    hours: int
    headline_mae: Errors = Field(description="Mean of the per-station MAEs, as in ADR 0007")
    stations: list[StationAccuracy]


class Problem(BaseModel):
    """An error, as Problem Details (RFC 9457), sent as application/problem+json."""

    type: str = Field(description='"about:blank": the status code says what went wrong')
    title: str = Field(description="The HTTP status phrase, such as Not Found")
    status: int
    detail: str = Field(description="What went wrong with this request, for a person to read")
    errors: list[dict[str, str]] | None = Field(
        default=None, description="For 422 only: each invalid field and why"
    )
