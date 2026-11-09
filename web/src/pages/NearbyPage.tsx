import { useQuery } from "@tanstack/react-query";
import { api, type NearbyReading } from "../api/client";
import { CategoryBadge } from "../components/CategoryBadge";
import { Empty, ErrorMessage, Loading } from "../components/Status";
import { ago } from "../lib/time";
import styles from "./NearbyPage.module.css";

// Until the map (#90) asks for your location, start from downtown Oakland
const DEFAULT_PLACE = {
  name: "downtown Oakland",
  lat: 37.8053,
  lon: -122.2725,
};

export function NearbyPage() {
  const { lat, lon } = DEFAULT_PLACE;
  const nearby = useQuery({
    queryKey: ["nearest", lat, lon],
    queryFn: () => api.nearest({ lat, lon, radius_km: 50, limit: 20 }),
  });

  return (
    <section className={styles.section}>
      <div className={styles.intro}>
        <h1>Air near {DEFAULT_PLACE.name}</h1>
        <p className={styles.lede}>
          The closest sensors, nearest first, corrected to match the official
          monitors.
        </p>
      </div>

      {nearby.isPending ? (
        <Loading label="Loading readings…" />
      ) : nearby.isError ? (
        <ErrorMessage
          error={nearby.error}
          onRetry={() => void nearby.refetch()}
        />
      ) : nearby.data.data.length === 0 ? (
        <Empty>No sensors within 50 km.</Empty>
      ) : (
        <ul className={styles.list}>
          {nearby.data.data.map((item) => (
            <NearbyItem key={item.sensor.id} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

function NearbyItem({ item }: { item: NearbyReading }) {
  const { sensor, reading, distance_km } = item;
  return (
    <li className={styles.item}>
      <div className={styles.place}>
        <h2 className={styles.name}>{sensor.name ?? sensor.id}</h2>
        <p className={styles.meta}>
          {distance_km.toFixed(1)} km away ·{" "}
          {reading.stale ? "Stale, " : "Measured "}
          {ago(reading.observed_at)}
        </p>
      </div>
      <div className={styles.value}>
        <p>
          <span className={styles.number}>
            {reading.pm25_corrected.toFixed(1)}
          </span>{" "}
          <span className={styles.unit}>µg/m³</span>
        </p>
        <CategoryBadge value={reading.aqi_category} />
      </div>
    </li>
  );
}
