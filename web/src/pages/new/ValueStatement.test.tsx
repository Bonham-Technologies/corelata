import { useState } from "react";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { candidates, DISCOVERY_ID, discoveryView, project, source } from "../../test/fixtures";
import { renderRoute } from "../../test/render";
import { server } from "../../test/server";
import { ValueStatement } from "./ValueStatement";

const PAGE = `/new?project=${project.id}`;

function Host({ sourceIds }: { sourceIds: string[] }) {
  const [value, setValue] = useState("");
  return (
    <ValueStatement
      projectId={project.id}
      sourceIds={sourceIds}
      value={value}
      onChange={setValue}
    />
  );
}

it("suggests values from a discovery and fills the statement (test_suggest_value_fills_the_statement)", async () => {
  let polls = 0;
  server.use(
    http.post("*/api/discoveries", async ({ request }) => {
      // no audience hint is left out, not sent as "" (R-M17-6)
      expect(await request.text()).toBe(
        JSON.stringify({ project_id: project.id, source_ids: [source.id] }),
      );
      return HttpResponse.json(discoveryView(), { status: 202 });
    }),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      polls += 1;
      return HttpResponse.json(
        polls < 2
          ? discoveryView({ state: "running" })
          : discoveryView({ state: "completed", candidates }),
      );
    }),
  );
  const { user } = renderRoute(<Host sourceIds={[source.id]} />, PAGE);
  await user.click(screen.getByRole("button", { name: "Suggest value" }));
  expect(await screen.findByRole("status", { name: "Suggestions" })).toHaveTextContent(
    "Looking for value",
  );
  const list = await screen.findByRole("list", { name: "Suggested value statements" });
  expect(list.children).toHaveLength(2);
  expect(screen.getByText("shipping line planners")).toBeInTheDocument();
  expect(screen.getByText("Two units state the expansion directly.")).toBeInTheDocument();
  await user.click(screen.getAllByRole("button", { name: "Use this statement" })[1]!);
  expect(screen.getByRole("textbox", { name: "Value statement" })).toHaveValue(candidates[1]!.text);
});

it("keeps the discovery in the URL, so a reload reads it again (R-M16-14)", async () => {
  const other = "55555555-5555-5555-5555-555555555555";
  server.use(
    http.post("*/api/discoveries", () =>
      HttpResponse.json(discoveryView({ discovery_id: other }), { status: 202 }),
    ),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
    http.get(`*/api/discoveries/${other}`, () =>
      HttpResponse.json(discoveryView({ discovery_id: other, state: "running" })),
    ),
  );
  // a reload of a page that had started a discovery: no click, the URL names it
  const { router, user } = renderRoute(
    <Host sourceIds={[source.id]} />,
    `${PAGE}&discovery=${DISCOVERY_ID}`,
  );
  expect(
    await screen.findByRole("list", { name: "Suggested value statements" }),
  ).toBeInTheDocument();
  // a new discovery replaces it in the URL (no new history entry) and its state shows
  await user.click(screen.getByRole("button", { name: "Suggest value" }));
  await waitFor(() =>
    expect(router.state.location.search).toBe(`?project=${project.id}&discovery=${other}`),
  );
  expect(router.state.historyAction).toBe("REPLACE");
  expect(await screen.findByRole("status", { name: "Suggestions" })).toHaveTextContent(
    "Looking for value",
  );
});

it("shows a failed discovery's error and stops polling (test_failed_discovery_shows_the_error)", async () => {
  let polls = 0;
  server.use(
    http.post("*/api/discoveries", () => HttpResponse.json(discoveryView(), { status: 202 })),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      polls += 1;
      return HttpResponse.json(
        discoveryView({ state: "failed", error: "gate: model unreachable" }),
      );
    }),
  );
  const { user } = renderRoute(<Host sourceIds={[source.id]} />, PAGE);
  await user.click(screen.getByRole("button", { name: "Suggest value" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("gate: model unreachable");
  const seen = polls;
  await new Promise((r) => setTimeout(r, 1200));
  expect(polls).toBe(seen);
});

it("needs at least one source and shows a rejected request", async () => {
  renderRoute(<Host sourceIds={[]} />, PAGE);
  expect(screen.getByRole("button", { name: "Suggest value" })).toBeDisabled();
  expect(screen.getByText("Select at least one source to get suggestions.")).toBeInTheDocument();
  server.use(
    http.post("*/api/discoveries", () =>
      HttpResponse.json(
        { detail: `source ${source.id} not in project ${project.id}` },
        { status: 404 },
      ),
    ),
  );
  const { user } = renderRoute(<Host sourceIds={[source.id]} />, PAGE);
  await user.click(screen.getAllByRole("button", { name: "Suggest value" })[1]!);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("not in project"));
});

it("moves focus to the Suggestions heading once a discovery starts (M18 polish F1)", async () => {
  server.use(
    http.post("*/api/discoveries", () => HttpResponse.json(discoveryView(), { status: 202 })),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
  );
  const { user } = renderRoute(<Host sourceIds={[source.id]} />, PAGE);
  expect(screen.queryByRole("heading", { name: "Suggestions" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Suggest value" }));
  const heading = await screen.findByRole("heading", { name: "Suggestions" });
  await waitFor(() => expect(heading).toHaveFocus());
  expect(heading).toHaveAttribute("tabindex", "-1");
});

it("does not take focus for a discovery already in the URL", async () => {
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
  );
  renderRoute(<Host sourceIds={[source.id]} />, `${PAGE}&discovery=${DISCOVERY_ID}`);
  const heading = await screen.findByRole("heading", { name: "Suggestions" });
  await screen.findByRole("list", { name: "Suggested value statements" });
  expect(heading).not.toHaveFocus();
});

it("bounds the statement at the API's 4,000 characters and counts near the limit (CRL-83)", async () => {
  const { user } = renderRoute(<Host sourceIds={[source.id]} />, PAGE);
  const box = screen.getByRole("textbox", { name: "Value statement" });
  expect(box).toHaveAttribute("maxLength", "4000");
  fireEvent.change(box, { target: { value: "x".repeat(3599) } });
  expect(screen.queryByText(/of 4,000 characters/)).toBeNull();
  expect(box).not.toHaveAttribute("aria-describedby");
  await user.type(box, "y");
  expect(screen.getByText("3,600 of 4,000 characters")).toBeInTheDocument();
  expect(box).toHaveAccessibleDescription("3,600 of 4,000 characters");
});
