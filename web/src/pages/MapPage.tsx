import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useMemo, useState } from "react";
import { NavLink } from "react-router";
import { allLatest, type SensorDetail } from "../api/client";
import { CategoryBadge } from "../components/CategoryBadge";
import { ErrorMessage, Loading } from "../components/Status";
import { CATEGORIES, category } from "../lib/aqi";
import { closest, distanceKm, type Point } from "../lib/geo";
import { ago } from "../lib/time";
import styles from "./MapPage.module.css";

const SensorMap = lazy(() => import("../components/SensorMap"));

interface Place extends Point {
  name: string;
  isYou: boolean;
}

// Until you share your location, start from downtown Oakland, the middle of the network
const DOWNTOWN_OAKLAND: Place = {
  name: "downtown Oakland",
  lat: 37.8053,
  lon: -122.2725,
  isYou: false,
};

type Locating = "idle" | "locating" | "denied" | "far";

// Farther than this from every sensor, you are outside the area AirSight covers
const COVERAGE_KM = 50;

const position = (sensor: SensorDetail): Point => ({
  lat: sensor.latitude,
  lon: sensor.longitude,
});

export function MapPage() {
  const latest = useQuery({ queryKey: ["latest"], queryFn: allLatest });
  const [place, setPlace] = useState<Place>(DOWNTOWN_OAKLAND);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [locating, setLocating] = useState<Locating>("idle");

  const sensors = useMemo(() => latest.data ?? [], [latest.data]);
  const nearest = useMemo(() => {
    const live = sensors
      .filter((sensor) => sensor.latest_reading && !sensor.latest_reading.stale)
      .map((sensor) => ({ ...position(sensor), sensor }));
    return closest(live, place)?.sensor;
  }, [sensors, place]);
  const selected =
    sensors.find((sensor) => sensor.id === chosenId) ?? nearest ?? null;

  // Picking a sensor answers any location message, so clear it
  function choose(sensorId: string) {
    setChosenId(sensorId);
    setLocating("idle");
  }

  function locateMe() {
    if (!navigator.geolocation) {
      setLocating("denied");
      return;
    }
    setLocating("locating");
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const you = { lat: coords.latitude, lon: coords.longitude };
        const closestSensor = closest(sensors.map(position), you);
        if (!closestSensor || distanceKm(closestSensor, you) > COVERAGE_KM) {
          setLocating("far");
          return;
        }
        setPlace({ name: "you", ...you, isYou: true });
        setChosenId(null); // show the sensor nearest to you
        setLocating("idle");
      },
      () => setLocating("denied"),
      { maximumAge: 10 * 60_000, timeout: 10_000 },
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.mapArea}>
        {sensors.length > 0 && (
          <Suspense fallback={<div className={styles.mapLoading} />}>
            <SensorMap
              sensors={sensors}
              selectedId={selected?.id ?? null}
              onSelect={choose}
              focus={selected ? position(selected) : place}
              you={place.isYou ? place : null}
            />
          </Suspense>
        )}
        <div className={styles.overlay}>
          <button
            type="button"
            className={styles.locate}
            onClick={locateMe}
            disabled={locating === "locating" || sensors.length === 0}
          >
            <span className={styles.locateIcon} aria-hidden="true" />
            {locating === "locating" ? "Finding you…" : "Use my location"}
          </button>
          <Legend sensors={sensors} />
        </div>
      </div>

      <aside className={styles.panel} aria-label="Selected sensor">
        {latest.isPending ? (
          <Loading label="Loading sensors…" />
        ) : latest.isError ? (
          <ErrorMessage
            error={latest.error}
            onRetry={() => void latest.refetch()}
          />
        ) : !selected ? (
          <p className={styles.note}>No sensors are reporting right now.</p>
        ) : (
          <SensorSummary
            key={selected.id}
            sensor={selected}
            place={place}
            isNearest={selected.id === nearest?.id}
          />
        )}
        {locating === "far" && (
          <p className={styles.note} role="status">
            AirSight covers the San Francisco Bay Area, and you're outside it,
            so the map stays on {DOWNTOWN_OAKLAND.name}.
          </p>
        )}
        {locating === "denied" && (
          <p className={styles.note} role="status">
            We couldn't get your location, so the map starts from{" "}
            {DOWNTOWN_OAKLAND.name}. You can allow it in your browser's site
            settings.
          </p>
        )}
      </aside>
    </div>
  );
}

function SensorSummary({
  sensor,
  place,
  isNearest,
}: {
  sensor: SensorDetail;
  place: Place;
  isNearest: boolean;
}) {
  const reading = sensor.latest_reading;
  const km = distanceKm(position(sensor), place);
  return (
    <div className={styles.summary}>
      <p className={styles.meta}>
        <span>
          {isNearest ? "Nearest sensor" : "Sensor"} · {km.toFixed(1)} km from{" "}
          {place.name}
        </span>
        {reading && <span>Updated {ago(reading.observed_at)}</span>}
      </p>
      <div className={styles.headline}>
        <div className={styles.title}>
          <h1 className={styles.name}>{sensor.name ?? sensor.id}</h1>
          {reading && <CategoryBadge value={reading.aqi_category} />}
        </div>
        {reading && (
          <p className={styles.value}>
            <span className={styles.number}>
              {reading.pm25_corrected.toFixed(1)}
            </span>
            <span className={styles.unit}>µg/m³</span>
          </p>
        )}
      </div>
      {!reading ? (
        <p>
          Our quality checks found this sensor unreliable, so we don't show its
          readings.
        </p>
      ) : reading.stale ? (
        <p>
          This sensor hasn't reported for over 6 hours, so this reading may be
          out of date.
        </p>
      ) : (
        <p>{category(reading.aqi_category).advice}</p>
      )}
      <NavLink to={`/sensors/${sensor.id}`} className={styles.details}>
        See details and the last 24 hours
      </NavLink>
    </div>
  );
}

/** Only the categories on the map today, so the legend stays short. */
function Legend({ sensors }: { sensors: SensorDetail[] }) {
  const shown = new Set(
    sensors.map((sensor) => sensor.latest_reading?.aqi_category),
  );
  const outOfService = sensors.some((sensor) => !sensor.latest_reading);
  return (
    <ul className={styles.legend} aria-label="Legend">
      {Object.values(CATEGORIES)
        .filter((item) => shown.has(item.key))
        .map((item) => (
          <li key={item.key} className={styles.chip}>
            <span
              className={styles.swatch}
              style={{ background: item.colour }}
            />
            {item.label}
          </li>
        ))}
      {outOfService && (
        <li className={styles.chip}>
          <span className={`${styles.swatch} ${styles.hollow}`} />
          Out of service
        </li>
      )}
    </ul>
  );
}
