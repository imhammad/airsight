import type { RouteObject } from "react-router";
import { Layout } from "./components/Layout";
import { NearbyPage } from "./pages/NearbyPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <NearbyPage /> },
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
