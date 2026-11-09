import type { RouteObject } from "react-router";
import { Layout } from "./components/Layout";
import { MapPage } from "./pages/MapPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { SensorPage } from "./pages/SensorPage";

/** Set on a route whose page fills the screen edge to edge, like the map. */
export interface RouteHandle {
  fullBleed?: boolean;
}

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      {
        index: true,
        element: <MapPage />,
        handle: { fullBleed: true } satisfies RouteHandle,
      },
      {
        path: "sensors/:sensorId",
        element: <SensorPage />,
      },
      {
        path: "accuracy",
        element: <PlaceholderPage title="Accuracy" issue={92} />,
      },
      {
        path: "about",
        element: <PlaceholderPage title="About AirSight" issue={92} />,
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
