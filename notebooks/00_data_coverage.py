"""Count official PM2.5 monitors that have a PurpleAir sensor nearby.

Run notebooks/00_fetch_coverage.sh first.
"""

import json
import math
from pathlib import Path

DATA = Path("data/coverage")


def km(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    p = math.pi / 180
    h = (
        math.sin((lat2 - lat1) * p / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    )
    return 12742 * math.asin(math.sqrt(h))


def purpleair(name):
    d = json.loads((DATA / name).read_text())
    if "data" not in d:
        raise SystemExit(f"{name}: {d}")
    i, j = d["fields"].index("latitude"), d["fields"].index("longitude")
    return [(r[i], r[j]) for r in d["data"] if r[i] is not None]


def report(name, monitors, sensors):
    print(f"\n== {name} ==")
    print(f"Official PM2.5 monitors: {len(monitors)}")
    print(f"PurpleAir outdoor sensors (active last hour): {len(sensors)}")
    for radius in (0.5, 1, 2):
        near = [sum(km(m, s) <= radius for s in sensors) for m in monitors]
        print(
            f"Within {radius} km: {sum(n > 0 for n in near)} monitors have a sensor nearby, "
            f"{sum(near)} sensor-monitor pairs"
        )


airnow = json.loads((DATA / "airnow_bay.json").read_text())
bay = list({r["SiteName"]: (r["Latitude"], r["Longitude"]) for r in airnow}.values())
report("San Francisco Bay Area", bay, purpleair("purpleair_bay.json"))

oaq = json.loads((DATA / "openaq_my.json").read_text())["results"]
my = [
    loc
    for loc in oaq
    if loc.get("isMonitor")
    and any(s["parameter"]["name"] == "pm25" for s in loc.get("sensors", []))
]
print(
    f"\nMalaysia: {len(my)} official OpenAQ monitors measure PM2.5 "
    f"(out of {len(oaq)} OpenAQ locations)"
)
kl = [
    (loc["coordinates"]["latitude"], loc["coordinates"]["longitude"])
    for loc in my
    if 2.9 <= loc["coordinates"]["latitude"] <= 3.3
    and 101.5 <= loc["coordinates"]["longitude"] <= 101.8
]
report("Kuala Lumpur", kl, purpleair("purpleair_kl.json"))
