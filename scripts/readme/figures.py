"""Draws the README figures as SVG, in light and dark, from the project's own data.

Run from the repo root (it needs web/node_modules for the fonts, so `npm ci` in web/ first):

    uv run --no-project --with fonttools==4.60.1 --with brotli==1.1.0 python scripts/readme/figures.py

It reads docs/assets/readme/hero.csv (export it from production with scripts/readme/hero.sql)
and writes hero, results and system figures to docs/assets/readme/, each as -light.svg and
-dark.svg. The fonts are the web app's own, cut down to the characters each figure uses and
embedded, because GitHub shows README images without loading any outside font.
"""

import base64
import csv
import io
from datetime import datetime
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "assets" / "readme"
FONTS = ROOT / "web" / "node_modules" / "@fontsource-variable"
SERIF_FILE = (
    FONTS / "source-serif-4" / "files" / "source-serif-4-latin-wght-normal.woff2"
)
UI_FILE = FONTS / "inter" / "files" / "inter-latin-wght-normal.woff2"

# The web app's tokens (web/src/styles/tokens.css), plus two muted tones for the baselines
THEMES = {
    "light": {
        "ground": "#f6f5f2",
        "surface": "#ffffff",
        "line": "#e3e1dc",
        "ink": "#1a1c1e",
        "secondary": "#545a61",
        "accent": "#1e5a85",
        "raw": "#9aa0a6",
        "epa": "#b07d32",
    },
    "dark": {
        "ground": "#111315",
        "surface": "#1a1d20",
        "line": "#2a2e32",
        "ink": "#ecedee",
        "secondary": "#a3a9af",
        "accent": "#86b6da",
        "raw": "#6b7178",
        "epa": "#d6a35c",
    },
}

# Final-test results, from docs/model-cards/airsight-correction-v1.md and
# docs/model-cards/airsight-forecast-v1.md (14 unseen days, mean of per-station errors)
RESULTS = [
    (
        "Correction, all hours",
        [("Raw sensor", 2.87, "raw"), ("EPA correction", 3.42, "epa")],
        2.50,
    ),
    (
        "Correction, moderate air",
        [("Raw sensor", 4.48, "raw"), ("EPA correction", 6.18, "epa")],
        3.89,
    ),
    (
        "Forecast, next 24 hours",
        [("Persistence", 3.21, "raw"), ("Same hour yesterday", 3.24, "epa")],
        2.69,
    ),
]

LT = "\x3c"  # an opening angle bracket, kept out of the source so the markup is built only by E()


def E(tag: str, attrs: dict | None = None, *children: str) -> str:
    """One SVG element as text; attribute names use _ for -, and text children are escaped."""
    parts = "".join(
        f' {k.rstrip("_").replace("_", "-")}="{v}"' for k, v in (attrs or {}).items()
    )
    if not children:
        return f"{LT}{tag}{parts}/>"
    return f"{LT}{tag}{parts}>{''.join(children)}{LT}/{tag}>"


def esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace(LT, "&lt;").replace(">", "&gt;")


class Figure:
    def __init__(self, width: int, height: int, theme: dict[str, str]) -> None:
        self.width, self.height, self.t = width, height, theme
        self.items: list[str] = []
        self.serif_text: set[str] = set()
        self.ui_text: set[str] = set()

    def add(self, markup: str) -> None:
        self.items.append(markup)

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float,
        serif: bool = False,
        weight: int = 400,
        color: str = "ink",
        anchor: str = "start",
        spacing: str = "0",
    ) -> None:
        (self.serif_text if serif else self.ui_text).add(value)
        self.add(
            E(
                "text",
                {
                    "x": f"{x:.1f}",
                    "y": f"{y:.1f}",
                    "fill": self.t[color],
                    "font_size": size,
                    "font_weight": weight,
                    "text_anchor": anchor,
                    "letter_spacing": spacing,
                    "class_": "s" if serif else "u",
                },
                esc(value),
            )
        )

    def svg(self, label: str) -> str:
        style = (
            font_face("AirSight Serif", SERIF_FILE, self.serif_text)
            + font_face("AirSight UI", UI_FILE, self.ui_text)
            + ".s{font-family:'AirSight Serif',Georgia,serif}"
            + ".u{font-family:'AirSight UI',system-ui,sans-serif;font-variant-numeric:tabular-nums}"
        )
        return (
            E(
                "svg",
                {
                    "xmlns": "http://www.w3.org/2000/svg",
                    "viewBox": f"0 0 {self.width} {self.height}",
                    "width": self.width,
                    "height": self.height,
                    "role": "img",
                    "aria_label": esc(label),
                },
                E("title", None, esc(label)),
                E("style", None, style),
                E(
                    "rect",
                    {
                        "width": self.width,
                        "height": self.height,
                        "rx": 16,
                        "fill": self.t["ground"],
                    },
                ),
                *self.items,
            )
            + "\n"
        )


def font_face(family: str, path: Path, texts: set[str]) -> str:
    if not texts:
        return ""
    font = TTFont(path)
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["kern", "liga", "tnum", "lnum"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="".join(texts) + " 0123456789.")
    subsetter.subset(font)
    buffer = io.BytesIO()
    font.flavor = "woff2"
    font.save(buffer)
    data = base64.b64encode(buffer.getvalue()).decode()
    return (
        f"@font-face{{font-family:'{family}';font-weight:100 900;"
        f"src:url(data:font/woff2;base64,{data}) format('woff2')}}"
    )


def read_hero() -> tuple[str, list[datetime], list[float], list[float], list[float]]:
    with (OUT / "hero.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) < 24:
        raise SystemExit(
            f"hero.csv has {len(rows)} hours; export it again with scripts/readme/hero.sql"
        )
    times = [datetime.fromisoformat(r["time"]) for r in rows]
    return (
        rows[0]["station"],
        times,
        [float(r["official"]) for r in rows],
        [float(r["raw"]) for r in rows],
        [float(r["corrected"]) for r in rows],
    )


def mae(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


def nice_max(value: float) -> int:
    for step in (10, 20, 30, 40, 60, 80, 100, 150, 200):
        if value <= step:
            return step
    return int(value) + 1


def hero(theme: dict[str, str]) -> str:
    station, times, official, raw, corrected = read_hero()
    f = Figure(900, 300, theme)
    f.text(40, 92, "AirSight", size=54, serif=True, weight=600)
    f.text(40, 140, "Cheap air sensors, corrected", size=24, serif=True)
    f.text(40, 170, "to official accuracy.", size=24, serif=True)
    f.text(
        40,
        236,
        "San Francisco Bay Area, corrected every hour",
        size=13,
        color="secondary",
    )
    f.text(
        40, 256, "and scored live against official monitors", size=13, color="secondary"
    )

    x0, x1, y0, y1 = 470.0, 856.0, 44.0, 232.0
    top = nice_max(max(official + raw + corrected))
    n = len(times)

    def X(i: int) -> float:
        return x0 + i / (n - 1) * (x1 - x0)

    def Y(v: float) -> float:
        return y1 - v / top * (y1 - y0)

    for v in (0, top // 2, top):
        f.add(
            E(
                "line",
                {
                    "x1": x0,
                    "x2": x1,
                    "y1": f"{Y(v):.1f}",
                    "y2": f"{Y(v):.1f}",
                    "stroke": theme["line"],
                    "stroke_width": 1,
                },
            )
        )
        f.text(x1 + 8, Y(v) + 4, str(v), size=11, color="secondary")

    def path(values: list[float]) -> str:
        return " ".join(
            f"{'M' if i == 0 else 'L'}{X(i):.1f} {Y(v):.1f}"
            for i, v in enumerate(values)
        )

    lines = [
        ("raw", raw, 1.5, None),
        ("ink", official, 1.5, "4 3"),
        ("accent", corrected, 2.25, None),
    ]
    for color, values, width, dash in lines:
        attrs = {
            "d": path(values),
            "fill": "none",
            "stroke": theme[color],
            "stroke_width": width,
            "stroke_linejoin": "round",
            "stroke_linecap": "round",
        }
        if dash:
            attrs["stroke_dasharray"] = dash
        f.add(E("path", attrs))

    start, end = times[0], times[-1]
    span = (
        f"{start:%-d %b} to {end:%-d %b %Y}"
        if start.month != end.month
        else f"{start:%-d} to {end:%-d %b %Y}"
    )
    f.text(
        x0, 28, f"PM2.5 in µg/m³ at {station}, {span} (UTC)", size=11, color="secondary"
    )
    legend = [
        ("Raw sensor", "raw", None, 0),
        ("Official monitor", "ink", "4 3", 112),
        ("AirSight", "accent", None, 254),
    ]
    for name, color, dash, offset in legend:
        lx = x0 + offset
        attrs = {
            "x1": lx,
            "x2": lx + 18,
            "y1": 258,
            "y2": 258,
            "stroke": theme[color],
            "stroke_width": 2,
        }
        if dash:
            attrs["stroke_dasharray"] = dash
        f.add(E("line", attrs))
        f.text(lx + 24, 262, name, size=12, color="secondary")
    f.text(
        x0,
        284,
        f"Mean error over these hours: raw {mae(raw, official):.1f}, "
        f"AirSight {mae(corrected, official):.1f} µg/m³",
        size=12,
        color="secondary",
    )
    return f.svg(
        f"PM2.5 at {station}: the raw sensor, the official monitor and AirSight's correction"
    )


def results(theme: dict[str, str]) -> str:
    f = Figure(900, 330, theme)
    left, right, top = 260.0, 860.0, 7
    rows_y = (92, 172, 252)

    def X(v: float) -> float:
        return left + v / top * (right - left)

    for v in range(top + 1):
        f.add(
            E(
                "line",
                {
                    "x1": f"{X(v):.1f}",
                    "x2": f"{X(v):.1f}",
                    "y1": 56,
                    "y2": 290,
                    "stroke": theme["line"],
                    "stroke_width": 1,
                },
            )
        )
        f.text(X(v), 312, str(v), size=11, color="secondary", anchor="middle")
    f.text(
        left,
        36,
        "Mean error in µg/m³ on 14 days no model saw, lower is better",
        size=12,
        color="secondary",
    )

    for (label, baselines, ours), y in zip(RESULTS, rows_y, strict=True):
        f.text(32, y + 6, label, size=17, serif=True)
        values = [v for _, v, _ in baselines] + [ours]
        f.add(
            E(
                "line",
                {
                    "x1": f"{X(min(values)):.1f}",
                    "x2": f"{X(max(values)):.1f}",
                    "y1": y,
                    "y2": y,
                    "stroke": theme["secondary"],
                    "stroke_width": 1,
                    "stroke_opacity": "0.5",
                },
            )
        )
        # Labels sit above the dots and alternate sides when two baselines are close together
        ordered = sorted(baselines, key=lambda b: b[1])
        for i, (name, value, color) in enumerate(ordered):
            f.add(
                E(
                    "circle",
                    {"cx": f"{X(value):.1f}", "cy": y, "r": 5.5, "fill": theme[color]},
                )
            )
            close = len(ordered) == 2 and abs(ordered[1][1] - ordered[0][1]) < 0.8
            anchor = ("end" if i == 0 else "start") if close else "middle"
            dx = (-4 if i == 0 else 4) if close else 0
            f.text(
                X(value) + dx,
                y - 14,
                f"{name} {value:.2f}",
                size=11,
                color="secondary",
                anchor=anchor,
            )
        f.add(
            E(
                "circle",
                {"cx": f"{X(ours):.1f}", "cy": y, "r": 7, "fill": theme["accent"]},
            )
        )
        f.text(
            X(ours),
            y + 26,
            f"AirSight {ours:.2f}",
            size=13,
            weight=600,
            color="accent",
            anchor="middle",
        )
    return f.svg(
        "Mean error of AirSight against the raw sensor, the EPA correction and two forecast baselines"
    )


def system(theme: dict[str, str]) -> str:
    f = Figure(900, 260, theme)

    def box(
        x: float, y: float, w: float, title: str, sub: str, strong: bool = False
    ) -> None:
        f.add(
            E(
                "rect",
                {
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": 58,
                    "rx": 10,
                    "fill": theme["surface"],
                    "stroke": theme["accent" if strong else "line"],
                    "stroke_width": 1.5 if strong else 1,
                },
            )
        )
        f.text(x + 14, y + 25, title, size=13, weight=600)
        f.text(x + 14, y + 44, sub, size=11, color="secondary")

    def arrow(x1: float, y1: float, x2: float, y2: float) -> None:
        f.add(
            E(
                "line",
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "stroke": theme["secondary"],
                    "stroke_width": 1.2,
                },
            )
        )
        if x1 == x2:
            d = f"M{x2} {y2} l-4 {6 if y2 < y1 else -6} h8 z"
        else:
            d = f"M{x2} {y2} l-6 -4 v8 z"
        f.add(E("path", {"d": d, "fill": theme["secondary"]}))

    f.text(28, 30, "EVERY HOUR", size=11, color="secondary", spacing="0.08em")
    box(28, 44, 156, "PurpleAir", "low-cost sensors, A and B")
    box(28, 112, 156, "AirNow", "official monitors")
    box(28, 180, 156, "Open-Meteo", "temperature, humidity")
    box(236, 112, 156, "Ingestion", "Celery, quality checks")
    box(444, 112, 164, "TimescaleDB", "with PostGIS")
    box(444, 30, 164, "Models", "correction, forecast", strong=True)
    box(660, 112, 96, "API", "FastAPI /v1")
    box(776, 112, 96, "Web", "React")
    box(660, 186, 212, "Caddy and Tailscale Funnel", "the only public door")
    arrow(184, 73, 236, 128)
    arrow(184, 141, 236, 141)
    arrow(184, 209, 236, 154)
    arrow(392, 141, 444, 141)
    arrow(500, 112, 500, 88)
    arrow(552, 88, 552, 112)
    arrow(608, 141, 660, 141)
    arrow(756, 141, 776, 141)
    arrow(708, 170, 708, 186)
    arrow(824, 170, 824, 186)
    f.text(444, 206, "Prometheus, Grafana, Alertmanager", size=11, color="secondary")
    f.text(444, 222, "and MLflow stay private", size=11, color="secondary")
    return f.svg(
        "How AirSight works: sources, ingestion, database, models, API, web and the public door"
    )


def main() -> None:
    for path in (SERIF_FILE, UI_FILE):
        if not path.exists():
            raise SystemExit(
                f"missing {path.relative_to(ROOT)}; run npm ci in web/ first"
            )
    OUT.mkdir(parents=True, exist_ok=True)
    for name, draw in (("hero", hero), ("results", results), ("system", system)):
        for theme_name, theme in THEMES.items():
            target = OUT / f"{name}-{theme_name}.svg"
            target.write_text(draw(theme))
            print(
                f"wrote {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)"
            )


if __name__ == "__main__":
    main()
