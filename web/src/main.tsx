import "./fonts";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/shell.css";
import "./styles/new.css";
import "./styles/run.css";
import "./styles/review.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { makeQueryClient, Providers } from "./Providers";
import { routes } from "./routes";
import { applyTheme } from "./theme/theme";

applyTheme();

const router = createBrowserRouter(routes);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers client={makeQueryClient()}>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
