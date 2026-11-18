import { Navigate, type RouteObject } from "react-router";
import { Layout } from "./components/Layout";
import { NotFound } from "./components/NotFound";
import { RouteError } from "./components/RouteError";
import { NewRunPage } from "./pages/new/NewRunPage";
import { ReviewPage } from "./pages/review/ReviewPage";
import { RunPage } from "./pages/run/RunPage";
import { SettingsPage } from "./settings/SettingsPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    errorElement: <RouteError />, // the layout itself failed: no frame to keep
    children: [
      {
        // A page that throws while rendering is replaced inside the layout: the top bar stays.
        errorElement: <RouteError />,
        children: [
          { index: true, element: <Navigate to="/new" replace /> },
          { path: "new", element: <NewRunPage /> },
          { path: "runs/:runId", element: <RunPage /> },
          { path: "runs/:runId/review", element: <ReviewPage /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];
