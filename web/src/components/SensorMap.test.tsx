import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { BROKEN, LAKE_MERRITT, OCEANVIEW } from "../test/sensors";
import SensorMap from "./SensorMap";

// A stand-in for MapLibre: markers land in the page so the test can find them
const map = vi.hoisted(() => ({
  easeTo: vi.fn(),
  addControl: vi.fn(),
  setStyle: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("maplibre-gl", () => ({
  MapLibreMap: vi.fn(function () {
    return map;
  }),
  NavigationControl: vi.fn(),
  setWorkerUrl: vi.fn(),
  Marker: vi.fn(function ({ element }: { element: HTMLElement }) {
    return {
      setLngLat() {
        return this;
      },
      addTo() {
        document.body.append(element);
        return this;
      },
      remove: () => element.remove(),
      getElement: () => element,
    };
  }),
}));

const props = {
  sensors: [LAKE_MERRITT, OCEANVIEW, BROKEN],
  selectedId: "pa-1001",
  focus: { lat: 37.8021, lon: -122.2585 },
  you: null,
};

test("every sensor is a marker a screen reader can name", () => {
  render(<SensorMap {...props} onSelect={vi.fn()} />);

  expect(
    screen.getByRole("button", { name: "Lake Merritt, 6.3 µg/m³, Good" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(
    screen.getByRole("button", { name: /^Oceanview Neighborhood Assn, 9\.1/ }),
  ).toHaveAttribute("aria-pressed", "false");
  expect(
    screen.getByRole("button", { name: "Broken, out of service" }),
  ).toBeInTheDocument();
});

test("choosing a marker reports which sensor", () => {
  const onSelect = vi.fn();
  render(<SensorMap {...props} onSelect={onSelect} />);

  fireEvent.click(screen.getByRole("button", { name: /^Oceanview/ }));

  expect(onSelect).toHaveBeenCalledWith("pa-27359");
});

test("the map glides to the focus", () => {
  const { rerender } = render(<SensorMap {...props} onSelect={vi.fn()} />);
  map.easeTo.mockClear();

  rerender(
    <SensorMap
      {...props}
      onSelect={vi.fn()}
      focus={{ lat: 37.87, lon: -122.3 }}
    />,
  );

  expect(map.easeTo).toHaveBeenCalledWith(
    expect.objectContaining({ center: [-122.3, 37.87] }),
  );
});
