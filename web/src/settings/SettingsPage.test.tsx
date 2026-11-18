import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { DoctorCheck } from "../api/types";
import { deferred } from "../test/deferred";
import { expectNoEngineWords } from "../test/engine-words";
import { doctorReport, info, packs } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";
import { resetThemeForTests } from "../theme/theme";

let probes: string[] = [];

beforeEach(() => {
  probes = [];
  localStorage.clear();
  resetThemeForTests();
  server.use(
    http.get("*/api/system/doctor", ({ request }) => {
      probes.push(new URL(request.url).searchParams.get("probe") ?? "");
      return HttpResponse.json(doctorReport);
    }),
    http.get("*/api/packs", () => HttpResponse.json(packs)),
  );
});

it("is linked from the header, names the tab and chooses the theme (copied)", async () => {
  const { user, router } = renderApp("/new");
  await user.click(screen.getByRole("link", { name: "Settings" }));
  expect(router.state.location.pathname).toBe("/settings");
  expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  expect(document.title).toBe("Settings – Corelata");
  expect(screen.getByRole("radio", { name: "Match my computer" })).toBeChecked();
  await user.click(screen.getByRole("radio", { name: "Dark" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("corelata.theme")).toBe("dark");
});

it("says how the installation is doing without test completions, and runs a full check when asked", async () => {
  const { user } = renderApp("/settings");
  const status = await screen.findByRole("region", { name: "Status" });
  expect(
    await within(status).findByText("Everything is working. 1 note is under Technical details."),
  ).toBeInTheDocument();
  const live = within(status).getByRole("status");
  expect(live).toBeEmptyDOMElement(); // the check on opening is not announced
  server.use(
    http.get("*/api/system/doctor", ({ request }) => {
      probes.push(new URL(request.url).searchParams.get("probe") ?? "");
      return HttpResponse.json({
        ok: false,
        checks: [{ name: "model m1", status: "fail", message: "404", fix: "" }],
      });
    }),
  );
  await user.click(within(status).getByRole("button", { name: "Run a full check" }));
  await waitFor(() =>
    expect(live).toHaveTextContent(
      "The model server isn't answering. Reports can't be written until an administrator fixes it.",
    ),
  );
  expect(probes).toEqual(["false", "true"]);
  expect(screen.getByRole("table", { name: "Checks" })).toHaveTextContent("model m1");
});

it("says when the status cannot be read, and while and why a full check fails", async () => {
  const held = deferred();
  server.use(
    http.get("*/api/system/doctor", async ({ request }) => {
      if (new URL(request.url).searchParams.get("probe") !== "true") {
        return HttpResponse.json({ detail: "the database is unreachable" }, { status: 500 });
      }
      await held.promise;
      return HttpResponse.json({ detail: "the full check timed out" }, { status: 500 });
    }),
  );
  const { user } = renderApp("/settings");
  const status = await screen.findByRole("region", { name: "Status" });
  expect(await within(status).findByRole("alert")).toHaveTextContent("the database is unreachable");
  await user.click(within(status).getByRole("button", { name: "Run a full check" }));
  expect(await within(status).findByRole("button", { name: "Checking…" })).toBeDisabled();
  held.resolve();
  expect(await within(status).findByText("the full check timed out")).toBeInTheDocument();
  expect(within(status).getByRole("button", { name: "Run a full check" })).toBeEnabled();
});

it("keeps the technical details folded: version, sign-in, limits, packs and every check", async () => {
  server.use(
    http.get("*/api/system/info", () =>
      HttpResponse.json({ ...info, default_profile: "team-east", auth_mode: "trusted_header" }),
    ),
  );
  renderApp("/settings");
  const details = (await screen.findByText("Technical details")).closest("details")!;
  expect(details).not.toHaveAttribute("open");
  await waitFor(() => expect(details).toHaveTextContent("Version0.1.0"));
  expect(details).toHaveTextContent("Sign-inby the proxy (trusted_header)");
  expect(details).toHaveTextContent("Upload limit200 MB");
  expect(details).toHaveTextContent("Default standards packicd203-base");
  expect(details).toHaveTextContent("Default team profileteam-east");
  const list = await within(details).findByRole("list", { name: "Standards packs" });
  expect(list).toHaveTextContent("icd203-base 1.0: team-east, draft-west (draft)");
  expect(within(details).getByRole("table", { name: "Checks" })).toHaveTextContent(
    "run a full check to send a test completion",
  );
});

it("keeps the expert words to Technical details on the main view, in every state", async () => {
  const states: [string, DoctorCheck][] = [
    ["working", { name: "config", status: "pass", message: "ok", fix: "" }],
    ["model server", { name: "model m1 auditor schema", status: "fail", message: "404", fix: "" }],
    ["config", { name: "config", status: "fail", message: "backends.x: bad pack", fix: "" }],
    ["database", { name: "database", status: "fail", message: "down", fix: "" }],
    ["other", { name: "pack", status: "fail", message: "audit failed", fix: "" }],
  ];
  for (const [state, check] of states) {
    server.use(
      http.get("*/api/system/doctor", () =>
        HttpResponse.json({ ok: state === "working", checks: [check] }),
      ),
    );
    renderApp("/settings");
    const details = (await screen.findByText("Technical details")).closest("details")!;
    await within(details).findByRole("list", { name: "Standards packs" });
    await within(details).findByRole("table", { name: "Checks" });
    const main = screen.getByRole("main").cloneNode(true) as HTMLElement;
    main.querySelector("details")!.remove(); // Technical details may use the expert words
    expect(main, state).toHaveTextContent("Run a full check");
    expectNoEngineWords(main);
    cleanup();
  }
});

it("shows a pack that failed to load and a packs failure", async () => {
  server.use(
    http.get("*/api/packs", () =>
      HttpResponse.json([{ ...packs[0]!, profiles: [], error: "pack.yaml: bad" }]),
    ),
  );
  renderApp("/settings");
  expect(await screen.findByText("pack.yaml: bad", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "Standards packs" })).toHaveTextContent(
    /^icd203-base 1\.0 pack\.yaml: bad$/,
  );
  server.use(
    http.get("*/api/packs", () => HttpResponse.json({ detail: "packs offline" }, { status: 400 })),
  );
  renderApp("/settings");
  expect((await screen.findAllByRole("alert")).at(-1)).toHaveTextContent("packs offline");
});
