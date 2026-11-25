import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { noRuns, packs, project, resolvedPack, source, sources } from "../../test/fixtures";
import type { SourceView } from "../../api/types";
import { expectNoEngineWords } from "../../test/engine-words";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";
import { statedText } from "./SourceDetails";

const lexicon = {
  ...resolvedPack.lexicon,
  source_descriptors: ["open-source report", "official government publication"],
  source_access: ["direct", "indirect", "unknown"],
};

function serve(list: SourceView[]) {
  server.use(
    http.get("*/api/packs", () => HttpResponse.json(packs)),
    http.get("*/api/packs/icd203-base/resolved", () =>
      HttpResponse.json({ ...resolvedPack, lexicon }),
    ),
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
  );
}

it("states a source's details, suggesting the lexicon's terms (CRL-138)", async () => {
  const list: SourceView[] = [{ ...source, stated: { origin: "Varna Daily" } }, sources[1]!];
  serve(list);
  let sent: unknown = null;
  server.use(
    http.patch(`*/api/projects/${project.id}/sources/${source.id}`, async ({ request }) => {
      sent = await request.json();
      list[0] = { ...source, stated: { origin: "Varna Daily", access: "direct" } };
      return HttpResponse.json(list[0]);
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const region = await screen.findByRole("region", { name: "Sources" });
  expect(await within(region).findByText("You stated: origin")).toBeInTheDocument();
  expect(within(region).queryAllByText(/You stated/)).toHaveLength(1);
  await user.click(within(region).getByRole("button", { name: "Details of port.txt" }));
  const dialog = await screen.findByRole("dialog", { name: "Details of port.txt" });
  expect(within(dialog).getByLabelText("Origin")).toHaveValue("Varna Daily");
  expect(within(dialog).getByLabelText("Descriptor")).toHaveValue("");
  const access = within(dialog).getByLabelText("Access");
  await waitFor(() => expect(access).toHaveAttribute("list"));
  const terms = document.getElementById(access.getAttribute("list")!)!;
  expect([...terms.querySelectorAll("option")].map((o) => o.value)).toEqual(lexicon.source_access);
  expectNoEngineWords(dialog);
  await user.type(access, "direct");
  await user.click(within(dialog).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(sent).toEqual({
    descriptor: "",
    reliability_note: "",
    date_of_information: "",
    origin: "Varna Daily",
    access: "direct",
  });
  expect(await within(region).findByText("You stated: origin, access")).toBeInTheDocument();
});

it("shows the server's refusal and cancels without saving", async () => {
  serve([source]);
  let calls = 0;
  server.use(
    http.patch(`*/api/projects/${project.id}/sources/${source.id}`, () => {
      calls += 1;
      return HttpResponse.json(
        { detail: "source: descriptor 'gossip' is not in the lexicon" },
        { status: 422 },
      );
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  await user.click(await screen.findByRole("button", { name: "Details of port.txt" }));
  const dialog = await screen.findByRole("dialog", { name: "Details of port.txt" });
  await user.type(within(dialog).getByLabelText("Descriptor"), "gossip");
  await user.type(within(dialog).getByLabelText("Reliability note"), "Unchecked.");
  await user.click(within(dialog).getByRole("button", { name: "Save" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("descriptor 'gossip'");
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(calls).toBe(1);
  // opened again, the form starts from what the source has, not the unsaved edit
  await user.click(screen.getByRole("button", { name: "Details of port.txt" }));
  const again = await screen.findByRole("dialog", { name: "Details of port.txt" });
  expect(within(again).getByLabelText("Descriptor")).toHaveValue("");
  expect(within(again).queryByRole("alert")).toBeNull();
  fireEvent(again, new Event("cancel", { cancelable: true })); // Escape
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("names nothing for a source with nothing stated", () => {
  expect(statedText(source)).toBe("");
  expect(
    statedText({ ...source, stated: { reliability_note: "x", date_of_information: "2026" } }),
  ).toBe("You stated: reliability note, date of information");
});
