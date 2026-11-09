/** Distances on the Earth's surface, good to a few metres at city scale. */
export interface Point {
  lat: number;
  lon: number;
}

const EARTH_RADIUS_KM = 6371;
const radians = (degrees: number) => (degrees * Math.PI) / 180;

/** Great-circle (haversine) distance between two points, in km. */
export function distanceKm(a: Point, b: Point): number {
  const dLat = radians(b.lat - a.lat);
  const dLon = radians(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(radians(a.lat)) *
      Math.cos(radians(b.lat)) *
      Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(h));
}

/** The item closest to a point, or undefined when there are none. */
export function closest<T extends Point>(items: T[], to: Point): T | undefined {
  let best: T | undefined;
  let bestKm = Infinity;
  for (const item of items) {
    const km = distanceKm(item, to);
    if (km < bestKm) [best, bestKm] = [item, km];
  }
  return best;
}
