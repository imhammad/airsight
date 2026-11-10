import { useQuery } from "@tanstack/react-query";
import { NavLink } from "react-router";
import { api, type Accuracy } from "../api/client";
import { ErrorMessage, Loading } from "../components/Status";
import styles from "./AccuracyPage.module.css";

// The same window the raw fallback uses (ADR 0010), so this page agrees with the map
const DAYS = 14;

export function AccuracyPage() {
  const accuracy = useQuery({
    queryKey: ["accuracy", DAYS],
    queryFn: () => api.accuracy({ days: DAYS }),
  });

  return (
    <article className={styles.page}>
      {accuracy.isPending ? (
        <Loading label="Loading the latest scores…" />
      ) : accuracy.isError ? (
        <ErrorMessage
          error={accuracy.error}
          onRetry={() => void accuracy.refetch()}
        />
      ) : (
        <Scores accuracy={accuracy.data} />
      )}
      <p className={styles.note}>
        Where the correction does worse than the sensor's own reading, the map
        shows the raw reading and says so, until the model is retrained.{" "}
        <NavLink to="/about">How we measure this</NavLink>
      </p>
    </article>
  );
}

function Scores({ accuracy }: { accuracy: Accuracy }) {
  const { corrected, raw, epa } = accuracy.headline_mae;
  const stations = accuracy.stations;
  const better = stations.filter(
    (s) =>
      s.mae.corrected !== null &&
      s.mae.raw !== null &&
      s.mae.corrected < s.mae.raw,
  ).length;

  return (
    <>
      <header className={styles.intro}>
        <p className={styles.muted}>
          Last {DAYS} days · {accuracy.hours.toLocaleString("en-US")} hours ·{" "}
          {stations.length} official monitors
        </p>
        <h1>How close are we to the official monitors?</h1>
        <p className={styles.lead}>
          Average error, in µg/m³, measured only on hours the model never saw.
          Lower is better.
        </p>
      </header>

      {corrected === null || raw === null || epa === null ? (
        <p className={styles.card}>
          No hours have been scored in this window yet. Scores appear once
          official readings arrive for hours the model hasn't seen.
        </p>
      ) : (
        <div className={styles.card}>
          <Bar
            label="AirSight correction"
            value={corrected}
            max={Math.max(corrected, raw, epa)}
            ours
          />
          <Bar
            label="Raw sensor"
            value={raw}
            max={Math.max(corrected, raw, epa)}
          />
          <Bar
            label="EPA US-wide correction"
            value={epa}
            max={Math.max(corrected, raw, epa)}
          />
        </div>
      )}

      {stations.length > 0 && (
        <section className={styles.section}>
          <div className={styles.sectionTitle}>
            <h2>By monitor</h2>
            <p className={styles.small}>
              Better than raw at {better} of {stations.length}
            </p>
          </div>
          <ul className={styles.stations} aria-label="Monitors">
            {stations.map((s) => (
              <li key={s.station} className={styles.station}>
                <div>
                  <p>{s.station}</p>
                  <p className={styles.small}>
                    {s.mae.corrected?.toFixed(2) ?? "–"} corrected ·{" "}
                    {s.mae.raw?.toFixed(2) ?? "–"} raw
                  </p>
                </div>
                {s.source === "raw" ? (
                  <span className={styles.raw}>
                    <span className={styles.rawDot} aria-hidden="true" />
                    Showing raw
                  </span>
                ) : (
                  <span className={styles.corrected}>Corrected</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

/** One average error as a bar; the longest bar is the largest error. */
function Bar({
  label,
  value,
  max,
  ours = false,
}: {
  label: string;
  value: number;
  max: number;
  ours?: boolean;
}) {
  return (
    <div className={styles.bar}>
      <p className={ours ? styles.ours : undefined}>
        <span>{label}</span>
        <span>{value.toFixed(2)}</span>
      </p>
      <div className={styles.track}>
        <div
          className={ours ? `${styles.fill} ${styles.oursFill}` : styles.fill}
          style={{ width: `${(value / max) * 90}%` }}
        />
      </div>
    </div>
  );
}
