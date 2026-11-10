import { useQuery } from "@tanstack/react-query";
import { NavLink } from "react-router";
import { api, type ModelInfo } from "../api/client";
import { modelLabel } from "../lib/describe";
import styles from "./AboutPage.module.css";

const REPO = "https://github.com/imhammad/airsight";

/** How AirSight works, in plain words, with the current model's own numbers. */
export function AboutPage() {
  const model = useQuery({ queryKey: ["model"], queryFn: api.model });

  return (
    <article className={styles.page}>
      <header className={styles.intro}>
        <h1>How AirSight works</h1>
        <p className={styles.lead}>
          Low-cost PurpleAir sensors are on thousands of homes, but their
          readings drift from the official monitors, most of all in humid air.
          AirSight learns how they differ, corrects every reading, and checks
          itself in public.
        </p>
      </header>

      <section className={styles.section}>
        <h2>The data</h2>
        <p>
          Every 3 hours we collect readings from the PurpleAir sensors in the
          San Francisco Bay Area that sit within 1 km of an official monitor.
          The official readings come from the EPA's AirNow network, and the
          weather from Open-Meteo. Sensors that fail our quality checks, such as
          ones stuck at zero or reporting impossible values, are left out.
        </p>
      </section>

      <section className={styles.section}>
        <h2>The correction</h2>
        <p>
          A gradient-boosted model (LightGBM) takes a sensor's raw reading and
          humidity, plus the local temperature, humidity, wind and rain, and
          predicts what the official monitor would read.
        </p>
        {model.data && <ModelCard model={model.data} />}
      </section>

      <section className={styles.section}>
        <h2>How we test it</h2>
        <p>
          Each monitor is scored by a model trained without it, so the score
          shows how the correction does at a place it has never seen. The last
          14 days of data are held back and scored once, before a model is
          released. The headline number is the average of each monitor's error,
          so a monitor with many sensors doesn't count more than the others.
        </p>
        <p>
          After release, the <NavLink to="/accuracy">Accuracy</NavLink> page
          keeps scoring the live corrections against the official monitors,
          using only hours the model never saw.
        </p>
      </section>

      <section className={styles.section}>
        <h2>When we show the raw reading</h2>
        <p>
          A model can drift. Every 3 hours we compare the last 14 days near each
          monitor. Where the correction was further from the official monitor
          than the sensor's own reading, over at least 200 hours, the map shows
          the raw reading instead, as a white marker, and says so. It switches
          back on its own once the correction does better again.
        </p>
      </section>

      <section className={styles.section}>
        <h2>Limits</h2>
        <ul className={styles.list}>
          <li>
            The model hasn't seen wildfire smoke yet, so very high readings are
            less certain.
          </li>
          <li>
            Moderate hours tend to read a little low, and sensors near San
            Rafael read high.
          </li>
          <li>
            These are estimates for everyday decisions, not official
            measurements for regulatory use.
          </li>
        </ul>
      </section>

      <section className={styles.section}>
        <h2>Open source</h2>
        <p>
          The code, the data pipeline and every decision behind them are on{" "}
          <a href={REPO}>GitHub</a>. The data is free to use through the{" "}
          <a href={`${REPO}/blob/main/docs/API.md`}>AirSight API</a>.
        </p>
      </section>
    </article>
  );
}

function ModelCard({ model }: { model: ModelInfo }) {
  const test = model.final_test;
  return (
    <div className={styles.card}>
      <p className={styles.cardTitle}>
        <span>Current model</span>
        <span>{modelLabel(model.model_version)}</span>
      </p>
      {test && (
        <dl className={styles.facts}>
          <div>
            <dt>Error on the held-back 14 days</dt>
            <dd>{test.headline_mae.toFixed(2)} µg/m³</dd>
          </div>
          <div>
            <dt>Raw sensors on the same days</dt>
            <dd>{test.raw_headline_mae.toFixed(2)} µg/m³</dd>
          </div>
          <div>
            <dt>EPA US-wide correction</dt>
            <dd>{test.epa_headline_mae.toFixed(2)} µg/m³</dd>
          </div>
        </dl>
      )}
      <a href={model.model_card} className={styles.cardLink}>
        Read the model card
      </a>
    </div>
  );
}
