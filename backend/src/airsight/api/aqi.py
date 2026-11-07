"""US EPA AQI categories for PM2.5, with the 2024 breakpoints (ADR 0008)."""

# Upper end of each category in µg/m³; anything above the last one is hazardous
BREAKPOINTS = [
    (9.0, "good"),
    (35.4, "moderate"),
    (55.4, "unhealthy_sensitive"),
    (125.4, "unhealthy"),
    (225.4, "very_unhealthy"),
]


def round_pm25(pm25: float) -> float:
    """PM2.5 as the API reports it: one decimal."""
    return round(pm25, 1)


def aqi_category(pm25: float) -> str:
    """The category of the value the API reports, so the number and the category always agree."""
    reported = round_pm25(pm25)
    for upper, category in BREAKPOINTS:
        if reported <= upper:
            return category
    return "hazardous"
