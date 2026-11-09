import { category } from "../lib/aqi";
import styles from "./CategoryBadge.module.css";

/** The AQI category as a coloured pill that always carries its name (ADR 0009). */
export function CategoryBadge({ value }: { value: string }) {
  const { label, colour, labelColour } = category(value);
  return (
    <span
      className={styles.badge}
      style={{ background: colour, color: labelColour }}
    >
      {label}
    </span>
  );
}
