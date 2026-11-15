import { useQuery } from "@tanstack/react-query";
import { NavLink } from "react-router";
import { api, type Accuracy, type ForecastAccuracy } from "../api/client";
import { ErrorMessage, Loading } from "../components/Status";
import styles from "./AccuracyPage.module.css";

// The same window the raw fallback uses (ADR 0010), so this page agrees with the map
const DAYS = 14;
// A week of forecasts: each hour is forecast 8 times a day, so this is plenty (ADR 0012)
const FORECAST_DAYS = 7;

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
      {/* Only once the scores are in, so the note doesn't jump down when they arrive */}
      {!accuracy.isPending && (
        <p className={styles.note}>
          Where the correction does worse than the sensor's own reading, the map
          shows the raw reading and says so, until the model is retrained.{" "}
          <NavLink to="/about">How we measure this</NavLink>
        </p>
      )}
      {!accuracy.isPending && <ForecastSection />}
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

/** How the 24-hour forecast did against two guesses that need no model (ADR 0012). */
function ForecastSection() {
  const scores = useQuery({
    queryKey: ["accuracy", "forecast", FORECAST_DAYS],
    queryFn: () => api.forecastAccuracy({ days: FORECAST_DAYS }),
  });

  return (
    <section className={styles.forecast} aria-labelledby="forecast-heading">
      <header className={styles.intro}>
        {scores.isSuccess && scores.data.hours > 0 && (
          <p className={styles.muted}>
            Last {FORECAST_DAYS} days ·{" "}
            {scores.data.hours.toLocaleString("en-US")} forecast hours ·{" "}
            {scores.data.stations.length} official monitor
            {scores.data.stations.length === 1 ? "" : "s"}
          </p>
        )}
        <h2 id="forecast-heading" className={styles.heading}>
          And the next 24 hours?
        </h2>
        <p className={styles.lead}>
          Average error of the most likely value, in µg/m³, once the official
          monitor reports. Compared with two simple guesses that need no model.
        </p>
      </header>
      {scores.isPending ? (
        <Loading label="Loading the forecast scores…" />
      ) : scores.isError ? (
        <ErrorMessage
          error={scores.error}
          onRetry={() => void scores.refetch()}
        />
      ) : (
        <ForecastScores scores={scores.data} />
      )}
    </section>
  );
}

const HORIZONS: Record<string, string> = {
  "1-6": "1 to 6 hours ahead",
  "7-12": "7 to 12 hours ahead",
  "13-24": "13 to 24 hours ahead",
};

function percent(share: number | null): string {
  return share === null ? "–" : `${Math.round(share * 100)}%`;
}

function ForecastScores({ scores }: { scores: ForecastAccuracy }) {
  const { forecast, persistence, same_hour_yesterday } = scores.headline_mae;
  if (forecast === null || persistence === null || same_hour_yesterday === null)
    return (
      <p className={styles.card}>
        No forecast hours have been scored in this window yet. Scores appear
        once the official monitors report for the hours the forecast covered.
      </p>
    );

  const max = Math.max(forecast, persistence, same_hour_yesterday);
  return (
    <>
      <div className={styles.card}>
        <Bar label="AirSight forecast" value={forecast} max={max} ours />
        <Bar
          label="The monitor's reading, unchanged"
          value={persistence}
          max={max}
        />
        <Bar
          label="Same hour yesterday"
          value={same_hour_yesterday}
          max={max}
        />
        <p className={styles.coverage}>
          The likely range held the real value{" "}
          <strong>{percent(scores.coverage)}</strong> of the time. We aim for
          80%.
        </p>
      </div>
      <section className={styles.section}>
        <div className={styles.sectionTitle}>
          <h2>By hours ahead</h2>
          <p className={styles.small}>Error and how often the range held</p>
        </div>
        <ul className={styles.stations} aria-label="Forecast by hours ahead">
          {scores.by_horizon.map((group) => (
            <li key={group.hours_ahead} className={styles.station}>
              <div>
                <p>{HORIZONS[group.hours_ahead]}</p>
                <p className={styles.small}>
                  {group.mae.forecast?.toFixed(2) ?? "–"} forecast ·{" "}
                  {group.mae.persistence?.toFixed(2) ?? "–"} unchanged
                </p>
              </div>
              <span className={styles.small}>
                Range held {percent(group.coverage)}
              </span>
            </li>
          ))}
        </ul>
      </section>
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
