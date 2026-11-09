/** US EPA PM2.5 categories (2024 breakpoints) as the app shows them (ADR 0009). */
export type CategoryKey =
  | "good"
  | "moderate"
  | "unhealthy_sensitive"
  | "unhealthy"
  | "very_unhealthy"
  | "hazardous";

export interface Category {
  key: CategoryKey;
  label: string;
  colour: string;
  labelColour: string;
  advice: string;
}

export const CATEGORIES: Record<CategoryKey, Category> = {
  good: {
    key: "good",
    label: "Good",
    colour: "var(--aqi-good)",
    labelColour: "var(--aqi-dark-label)",
    advice: "Air quality is good. A great day to be active outside.",
  },
  moderate: {
    key: "moderate",
    label: "Moderate",
    colour: "var(--aqi-moderate)",
    labelColour: "var(--aqi-dark-label)",
    advice:
      "Acceptable for most people. If you're unusually sensitive, take it easier on long, hard exercise outside.",
  },
  unhealthy_sensitive: {
    key: "unhealthy_sensitive",
    label: "Unhealthy for sensitive groups",
    colour: "var(--aqi-unhealthy-sensitive)",
    labelColour: "var(--aqi-dark-label)",
    advice:
      "Children, older adults and people with asthma or heart or lung disease should take it easier outside.",
  },
  unhealthy: {
    key: "unhealthy",
    label: "Unhealthy",
    colour: "var(--aqi-unhealthy)",
    labelColour: "var(--aqi-light-label)",
    advice:
      "Everyone should cut back on long or hard activity outside. Sensitive groups should avoid it.",
  },
  very_unhealthy: {
    key: "very_unhealthy",
    label: "Very unhealthy",
    colour: "var(--aqi-very-unhealthy)",
    labelColour: "var(--aqi-light-label)",
    advice:
      "Everyone should avoid long or hard activity outside. Sensitive groups should stay indoors.",
  },
  hazardous: {
    key: "hazardous",
    label: "Hazardous",
    colour: "var(--aqi-hazardous)",
    labelColour: "var(--aqi-light-label)",
    advice:
      "Everyone should stay indoors and keep activity low. Follow local health advice.",
  },
};

/** The category for an API value. Throws on an unknown one, so a contract change is loud. */
export function category(key: string): Category {
  if (!(key in CATEGORIES)) throw new Error(`Unknown AQI category: ${key}`);
  return CATEGORIES[key as CategoryKey];
}
