import "maplibre-gl/dist/maplibre-gl.css";
import {
  MapLibreMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
} from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useCallback, useEffect, useRef, useState } from "react";
import type { SensorDetail } from "../api/client";
import { category } from "../lib/aqi";
import { describeSensor } from "../lib/describe";
import type { Point } from "../lib/geo";
import styles from "./SensorMap.module.css";

// MapLibre looks for its worker next to its own file, which Vite moves; point at Vite's copy
setWorkerUrl(workerUrl);

// Free OpenStreetMap vector tiles, no key or tracking (ADR 0009)
const MAP_STYLES = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
};

const prefers = (query: string) => window.matchMedia?.(query).matches ?? false;
const mapStyle = () =>
  prefers("(prefers-color-scheme: dark)") ? MAP_STYLES.dark : MAP_STYLES.light;

export interface SensorMapProps {
  sensors: SensorDetail[];
  selectedId: string | null;
  onSelect: (sensorId: string) => void;
  /** The point to keep in view: the selected sensor, or the place you asked about */
  focus: Point;
  /** Your location, once you share it */
  you: Point | null;
}

function markerElement(sensor: SensorDetail): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = styles.marker;
  button.setAttribute("aria-label", describeSensor(sensor));
  const reading = sensor.latest_reading;
  if (sensor.health === "excluded" || !reading) {
    button.classList.add(styles.excluded);
  } else {
    button.style.setProperty("--colour", category(reading.aqi_category).colour);
    if (reading.source === "raw") button.classList.add(styles.raw);
    if (reading.stale) button.classList.add(styles.stale);
  }
  const dot = document.createElement("span");
  dot.className = styles.dot;
  button.append(dot);
  return button;
}

/** The sensor map. Kept in its own file so MapLibre (about 300 kB gzipped) loads only with the map. */
export default function SensorMap({
  sensors,
  selectedId,
  onSelect,
  focus,
  you,
}: SensorMapProps) {
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef(new Map<string, Marker>());
  const select = useRef(onSelect);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    select.current = onSelect;
  }, [onSelect]);

  const start = useRef(focus);

  // Create the map when its element mounts and remove it when it unmounts (a React 19 ref
  // callback with cleanup); follow the light or dark theme meanwhile
  const mount = useCallback((element: HTMLDivElement) => {
    let created: MapLibreMap;
    try {
      created = new MapLibreMap({
        container: element,
        style: mapStyle(),
        center: [start.current.lon, start.current.lat],
        zoom: 11,
        attributionControl: { compact: true },
      });
    } catch {
      setFailed(true); // no WebGL: the panel still shows the nearest reading
      return;
    }
    created.addControl(new NavigationControl({ showCompass: false }));
    map.current = created;

    const scheme = window.matchMedia?.("(prefers-color-scheme: dark)");
    const restyle = () => created.setStyle(mapStyle());
    scheme?.addEventListener("change", restyle);
    return () => {
      scheme?.removeEventListener("change", restyle);
      created.remove();
      map.current = null;
    };
  }, []);

  // One marker per sensor, rebuilt when the readings change
  useEffect(() => {
    const current = map.current;
    if (!current) return;
    const placed = markers.current;
    for (const sensor of sensors) {
      const element = markerElement(sensor);
      element.addEventListener("click", () => select.current(sensor.id));
      placed.set(
        sensor.id,
        new Marker({ element })
          .setLngLat([sensor.longitude, sensor.latitude])
          .addTo(current),
      );
    }
    return () => {
      for (const marker of placed.values()) marker.remove();
      placed.clear();
    };
  }, [sensors]);

  // Mark the selected sensor
  useEffect(() => {
    for (const [id, marker] of markers.current) {
      const element = marker.getElement();
      const selected = id === selectedId;
      element.classList.toggle(styles.selected, selected);
      element.setAttribute("aria-pressed", String(selected));
    }
  }, [selectedId, sensors]);

  // Glide to the focus, or jump when you prefer less motion
  useEffect(() => {
    map.current?.easeTo({
      center: [focus.lon, focus.lat],
      duration: prefers("(prefers-reduced-motion: reduce)") ? 0 : 400,
    });
  }, [focus.lat, focus.lon]);

  // A quiet dot where you are
  useEffect(() => {
    const current = map.current;
    if (!current || !you) return;
    const element = document.createElement("span");
    element.className = styles.you;
    element.setAttribute("role", "img");
    element.setAttribute("aria-label", "You are here");
    const marker = new Marker({ element })
      .setLngLat([you.lon, you.lat])
      .addTo(current);
    return () => {
      marker.remove();
    };
  }, [you]);

  return (
    <div className={styles.frame}>
      <div
        ref={mount}
        className={styles.map}
        role="region"
        aria-label="Map of sensors"
      />
      {failed && (
        <p className={styles.failed}>
          Your browser can't show the map. The nearest reading is below.
        </p>
      )}
    </div>
  );
}
