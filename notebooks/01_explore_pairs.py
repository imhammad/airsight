# %% [markdown]
# # 01: Explore paired sensor and monitor data
#
# Questions:
# 1. How complete is the data?
# 2. Which sensors are broken, and how can we tell?
# 3. How far are raw PurpleAir readings from the official monitors?
# 4. Does humidity explain the error?
# 5. How good is the EPA's standard correction, the baseline AirSight must beat?
#
# Run from the repo root with the database running:
#     uv run --project backend --group notebooks python notebooks/01_explore_pairs.py
# The "# %%" lines split the file into cells, like a Jupyter notebook, but it stays
# a plain Python file: readable diffs in pull requests, and linted like other code.

# %%
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from airsight.core.db import get_engine

FIGURES = Path("docs/images/exploration")
FIGURES.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 120)

QUERY = """
SELECT
    m.name AS monitor,
    s.source_id AS sensor,
    round(p.distance_m) AS distance_m,
    l.time,
    l.pm25_a,
    l.pm25_b,
    l.humidity,
    r.pm25 AS official
FROM sensor_pairs p
JOIN sensors m ON m.id = p.reference_sensor_id
JOIN sensors s ON s.id = p.lowcost_sensor_id
JOIN lowcost_readings l ON l.sensor_id = p.lowcost_sensor_id
LEFT JOIN reference_readings r
    ON r.sensor_id = p.reference_sensor_id AND r.time = l.time
"""
df = pd.read_sql(QUERY, get_engine())
print(f"{len(df):,} sensor-hours from {df.sensor.nunique()} sensors")
print(f"{df.monitor.nunique()} monitors")
print(f"From {df.time.min()} to {df.time.max()}")

# %% [markdown]
# ## 1. Completeness
# A sensor that reported every hour has 100%. Gaps happen when a sensor loses
# power or Wi-Fi.

# %%
expected_hours = int((df.time.max() - df.time.min()) / pd.Timedelta(hours=1)) + 1
coverage = df.groupby("sensor").size() / expected_hours * 100
print(f"Expected hours per sensor: {expected_hours}")
print(f"Median coverage: {coverage.median():.0f}%")
print(f"Sensors under 75% coverage: {(coverage < 75).sum()} of {len(coverage)}")
print(f"Hours with no official reading to compare: {df.official.isna().mean():.1%}")

# %% [markdown]
# ## 2. Sensor health
# Each PurpleAir sensor has two laser counters, A and B. Healthy counters agree.
# The EPA treats an hour as unreliable when they differ by more than 5 µg/m³
# AND by more than 70%. We also look for impossible values (over 1,000 µg/m³)
# and counters stuck at zero.

# %%
difference = (df.pm25_a - df.pm25_b).abs()
mean_ab = (df.pm25_a + df.pm25_b) / 2
df["disagree"] = (difference > 5) & (difference / mean_ab > 0.7)
df["impossible"] = (df.pm25_a > 1000) | (df.pm25_b > 1000)
df["zero"] = (df.pm25_a == 0) & (df.pm25_b == 0)
df["missing_channel"] = df.pm25_a.isna() | df.pm25_b.isna()

health = df.groupby(["monitor", "sensor"]).agg(
    hours=("time", "size"),
    median_a=("pm25_a", "median"),
    median_b=("pm25_b", "median"),
    max_a=("pm25_a", "max"),
    max_b=("pm25_b", "max"),
    disagree=("disagree", "mean"),
    impossible=("impossible", "mean"),
    zero=("zero", "mean"),
)
problem = health[
    (health.disagree > 0.1) | (health.impossible > 0) | (health.zero > 0.5)
]
print(f"Sensors with a problem: {len(problem)} of {len(health)}")
print(problem.round(2).to_string())

# %% [markdown]
# ## 3. Raw readings against the official monitors
# Keep only trustworthy hours: both counters present and agreeing, no impossible
# values, not stuck at zero, and an official reading for the same hour.

# %%
clean = df[
    ~df.disagree
    & ~df.impossible
    & ~df.zero
    & ~df.missing_channel
    & df.official.notna()
    & df.humidity.notna()
].copy()
clean["raw"] = (clean.pm25_a + clean.pm25_b) / 2
print(f"Trustworthy hours: {len(clean):,} of {len(df):,} ({len(clean) / len(df):.0%})")


def summarise(estimate: pd.Series, name: str) -> None:
    error = estimate - clean.official
    print(
        f"{name:<16} mean error {error.mean():+5.2f}   "
        f"mean absolute error {error.abs().mean():5.2f}   "
        f"correlation {estimate.corr(clean.official):.2f}"
    )


# %% [markdown]
# ## 4. The EPA correction: the baseline to beat
# The EPA's US-wide correction (Barkjohn et al., 2021) adjusts the raw reading
# using the sensor's own humidity:
#     corrected = 0.524 × raw − 0.0862 × humidity + 5.75

# %%
clean["epa"] = 0.524 * clean.raw - 0.0862 * clean.humidity + 5.75
print("Errors against the official monitors (µg/m³):")
summarise(clean.raw, "Raw PurpleAir")
summarise(clean.epa, "EPA correction")

per_monitor = clean.groupby("monitor").agg(
    official=("official", "mean"),
    raw=("raw", "mean"),
    epa=("epa", "mean"),
    hours=("time", "size"),
)
print(per_monitor.round(1).to_string())

# %%
fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharex=True, sharey=True)
titles = {"raw": "Raw PurpleAir", "epa": "EPA correction"}
for ax, (column, title) in zip(axes, titles.items(), strict=True):
    ax.scatter(clean.official, clean[column], s=4, alpha=0.3)
    top = max(clean.official.max(), clean[column].max())
    ax.plot([0, top], [0, top], color="black", linewidth=1, label="perfect agreement")
    ax.set_title(title)
    ax.set_xlabel("Official monitor PM2.5 (µg/m³)")
axes[0].set_ylabel("Sensor PM2.5 (µg/m³)")
axes[0].legend()
fig.tight_layout()
fig.savefig(FIGURES / "raw_vs_epa.png", dpi=120)
plt.close(fig)

# %% [markdown]
# ## 5. Does humidity explain the error?
# Particles absorb water and swell in humid air, so the sensor's laser counts
# them as bigger. If that matters here, the raw error should change with humidity.

# %%
clean["humidity_band"] = pd.cut(clean.humidity, bins=[0, 40, 60, 80, 100])
by_humidity = (
    clean.assign(
        raw_error=clean.raw - clean.official, epa_error=clean.epa - clean.official
    )
    .groupby("humidity_band", observed=True)
    .agg(
        hours=("time", "size"),
        raw_error=("raw_error", "mean"),
        epa_error=("epa_error", "mean"),
    )
)
print(by_humidity.round(2).to_string())

fig, ax = plt.subplots(figsize=(6, 4))
by_humidity[["raw_error", "epa_error"]].plot.bar(ax=ax)
ax.axhline(0, color="black", linewidth=1)
ax.set_xlabel("Sensor humidity (%)")
ax.set_ylabel("Mean error (µg/m³)")
ax.set_title("Error by humidity")
fig.tight_layout()
fig.savefig(FIGURES / "error_by_humidity.png", dpi=120)
plt.close(fig)
print(f"Figures saved to {FIGURES}/")
