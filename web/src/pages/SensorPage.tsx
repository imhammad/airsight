import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { NavLink, useParams } from "react-router";
import { api, ApiError, type Forecast, type SensorDetail } from "../api/client";
import { CategoryBadge } from "../components/CategoryBadge";
import { ForecastChart } from "../components/ForecastChart";
import { HistoryChart } from "../components/HistoryChart";
import { ErrorMessage, Loading } from "../components/Status";
import { category } from "../lib/aqi";
import {
  modelLabel,
  MONITOR_OFFLINE_NOTE,
  NO_READING_NOTE,
  OUTSIDE_EXPERIENCE_NOTE,
  RAW_NOTE,
} from "../lib/describe";
import { summarize, upcoming } from "../lib/forecast";
import { ago, HOUR, startOfHour } from "../lib/time";
import styles from "./SensorPage.module.css";

export function SensorPage() {
  const { sensorId = "" } = useParams();
  // Fixed when the page opens, so the 24-hour window (and its cache key) stays put
  const [now] = useState(() => Date.now());
  const sensor = useQuery({
    queryKey: ["sensor", sensorId],
    queryFn: () => api.sensor(sensorId),
  });

  return (
    <article className={styles.page}>
      <div className={styles.top}>
        <NavLink to="/" className={styles.back}>
          <span aria-hidden="true">←</span> Map
        </NavLink>
        {sensor.data?.latest_reading && (
          <p className={styles.muted}>
            Updated {ago(sensor.data.latest_reading.observed_at, now)}
          </p>
        )}
      </div>

      {sensor.isPending ? (
        <Loading label="Loading the sensor…" />
      ) : sensor.isError ? (
        sensor.error instanceof ApiError && sensor.error.status === 404 ? (
          <div className={styles.intro}>
            <h1>Sensor not found</h1>
            <p className={styles.muted}>
              There's no sensor with the id {sensorId}. It may have been
              removed.
            </p>
          </div>
        ) : (
          <ErrorMessage
            error={sensor.error}
            onRetry={() => void sensor.refetch()}
          />
        )
      ) : (
        <SensorDetails sensor={sensor.data} now={now} />
      )}

      <NavLink to="/accuracy" className={styles.accuracy}>
        <span>How accurate is this?</span>
        <span aria-hidden="true">→</span>
      </NavLink>
    </article>
  );
}

function SensorDetails({ sensor, now }: { sensor: SensorDetail; now: number }) {
  const reading = sensor.latest_reading;
  const [, sourceId] = sensor.id.split("-");
  return (
    <>
      <div className={styles.intro}>
        <p className={styles.muted}>PurpleAir sensor {sourceId}</p>
        <h1>{sensor.name ?? sensor.id}</h1>
      </div>

      {sensor.health === "excluded" ? (
        <div className={styles.card}>
          <p className={styles.outOfService}>Out of service</p>
          <p>
            Our quality checks found this sensor unreliable, so we don't show
            its readings. Nearby sensors on the map still have theirs.
          </p>
        </div>
      ) : !reading ? (
        <div className={styles.card}>
          <p className={styles.outOfService}>No reading yet</p>
          <p>{NO_READING_NOTE}</p>
        </div>
      ) : (
        <>
          <div className={styles.card}>
            <div className={styles.headline}>
              <p className={styles.value}>
                <span className={styles.number}>{reading.pm25.toFixed(1)}</span>
                <span className={styles.unit}>µg/m³ PM2.5</span>
              </p>
              <CategoryBadge value={reading.aqi_category} />
            </div>
            <p className={styles.advice}>
              {reading.stale
                ? "This sensor hasn't reported for over 6 hours, so this reading may be out of date."
                : category(reading.aqi_category).advice}
            </p>
            {reading.source === "raw" && (
              <p className={styles.note}>{RAW_NOTE}</p>
            )}
            <dl className={styles.facts}>
              {reading.source === "raw" ? (
                <div>
                  <dt>Corrected value</dt>
                  <dd>{reading.pm25_corrected.toFixed(1)}</dd>
                </div>
              ) : (
                <div>
                  <dt>Sensor's own reading</dt>
                  <dd>{reading.pm25_raw?.toFixed(1) ?? "Not available"}</dd>
                </div>
              )}
              <div>
                <dt>Corrected by</dt>
                <dd>{modelLabel(reading.model_version)}</dd>
              </div>
            </dl>
          </div>
          <LastDay sensorId={sensor.id} now={now} />
          <NextDay sensorId={sensor.id} now={now} />
        </>
      )}
    </>
  );
}

function LastDay({ sensorId, now }: { sensorId: string; now: number }) {
  const start = new Date(startOfHour(now) - 23 * HOUR).toISOString();
  const end = new Date(startOfHour(now) + HOUR).toISOString();
  const history = useQuery({
    queryKey: ["history", sensorId, start],
    queryFn: () => api.history(sensorId, { start, end }),
  });

  return (
    <section className={styles.section}>
      <div className={styles.sectionTitle}>
        <h2>Last 24 hours</h2>
        <p className={styles.small}>Bay Area time</p>
      </div>
      {history.isPending ? (
        <Loading label="Loading the last 24 hours…" />
      ) : history.isError ? (
        <ErrorMessage
          error={history.error}
          onRetry={() => void history.refetch()}
        />
      ) : (
        <HistoryChart readings={history.data.data} now={now} />
      )}
    </section>
  );
}

function NextDay({ sensorId, now }: { sensorId: string; now: number }) {
  const forecast = useQuery({
    queryKey: ["forecast", sensorId],
    queryFn: () => api.forecast(sensorId),
  });

  return (
    <section className={styles.section}>
      <div className={styles.sectionTitle}>
        <h2>Next 24 hours</h2>
        <p className={styles.small}>Bay Area time</p>
      </div>
      {forecast.isPending ? (
        <Loading label="Loading the forecast…" />
      ) : forecast.isError ? (
        forecast.error instanceof ApiError && forecast.error.status === 404 ? (
          <p className={styles.note}>
            There's no forecast for this sensor yet. A new one is made every 3
            hours.
          </p>
        ) : (
          <ErrorMessage
            error={forecast.error}
            onRetry={() => void forecast.refetch()}
          />
        )
      ) : (
        <ForecastDetails forecast={forecast.data} now={now} />
      )}
    </section>
  );
}

function ForecastDetails({
  forecast,
  now,
}: {
  forecast: Forecast;
  now: number;
}) {
  const hours = upcoming(forecast.hours, now);
  if (hours.length === 0) {
    return (
      <p className={styles.note}>
        The latest forecast has run out. A new one is made every 3 hours.
      </p>
    );
  }
  return (
    <>
      <p className={styles.advice}>{summarize(hours)}</p>
      {forecast.stale && (
        <p className={styles.note}>
          This forecast was made over 6 hours ago, so it may be out of date.
        </p>
      )}
      {forecast.monitor_offline && (
        <p className={styles.note}>{MONITOR_OFFLINE_NOTE}</p>
      )}
      {hours.some((hour) => hour.outside_experience) && (
        <p className={styles.note}>{OUTSIDE_EXPERIENCE_NOTE}</p>
      )}
      <ForecastChart hours={hours} />
      <p className={styles.small}>
        The tick is the most likely value. The shaded range holds the real value
        about 8 times in 10. Made {ago(forecast.issued_at, now)} by{" "}
        {modelLabel(forecast.model_version)}.
      </p>
    </>
  );
}
