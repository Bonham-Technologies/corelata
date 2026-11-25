import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { info, packs } from "../../test/fixtures";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { RunOptions } from "./RunOptions";

/** The page's part: a chosen value, or null for the deployment's (here 2). */
function Host({
  spy = () => {},
  initial = null,
}: {
  spy?: (n: number | null) => void;
  initial?: string | null;
}) {
  const [profile, setProfile] = useState<string | null>(initial);
  const [n, setN] = useState<number | null>(null);
  const [guidance, setGuidance] = useState("");
  return (
    <RunOptions
      profile={profile}
      onProfile={setProfile}
      guidance={guidance}
      onGuidance={setGuidance}
      maxIterations={n ?? 2}
      onMaxIterations={(value) => {
        spy(value);
        setN(value);
      }}
    />
  );
}

it("keeps what is typed while the field has focus, and clamps the rounds to 0-10 on blur", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  const spy = vi.fn();
  const { user } = renderWithClient(<Host spy={spy} />);
  const fold = screen.getByText("More options").closest("details")!;
  expect(fold).not.toHaveAttribute("open"); // folded until asked (M18 spec §5.2)
  const box = screen.getByRole("spinbutton", { name: "Revision rounds" });
  await user.clear(box);
  await user.type(box, "99");
  expect(box).toHaveValue(99); // the draft, while typing
  expect(spy).toHaveBeenLastCalledWith(10); // what the page holds is always within 0-10
  await user.tab();
  expect(box).toHaveValue(10);
  expect(spy.mock.calls.flat().every((n) => n === null || (n >= 0 && n <= 10))).toBe(true);
});

it("retypes the rounds with no intermediate 0 (CRL-90)", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  const spy = vi.fn();
  const { user } = renderWithClient(<Host spy={spy} />);
  const box = screen.getByRole("spinbutton", { name: "Revision rounds" });
  await user.clear(box);
  expect(box).toHaveValue(null); // stays empty, not snapped to 0 or refilled
  await user.type(box, "3");
  expect(spy.mock.calls).toEqual([[null], [3]]);
  expect(box).toHaveValue(3);
});

it("follows the deployment's rounds again when the field is left empty (CRL-90)", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  const spy = vi.fn();
  const { user } = renderWithClient(<Host spy={spy} />);
  const box = screen.getByRole("spinbutton", { name: "Revision rounds" });
  await user.clear(box);
  await user.type(box, "5");
  await user.clear(box);
  await user.tab();
  expect(spy).toHaveBeenLastCalledWith(null);
  expect(box).toHaveValue(2); // the deployment's, shown once the field is left
});

it("rounds a fraction and never sends one", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  const spy = vi.fn();
  const { user } = renderWithClient(<Host spy={spy} />);
  const box = screen.getByRole("spinbutton", { name: "Revision rounds" });
  await user.clear(box);
  await user.type(box, "2.6");
  await user.tab();
  expect(box).toHaveValue(3);
  expect(spy.mock.calls.flat().every((n) => n === null || Number.isInteger(n))).toBe(true);
});

it("labels the empty option as no team profile, or the default profile when one is set", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  renderWithClient(<Host />);
  expect(await screen.findByRole("option", { name: "No team profile" })).toHaveValue("");
  cleanup();
  server.use(
    http.get("*/api/system/info", () =>
      HttpResponse.json({ ...info, default_profile: "team-east" }),
    ),
  );
  renderWithClient(<Host />);
  expect(await screen.findByRole("option", { name: "Default (team-east)" })).toHaveValue("");
});

it("goes back to no team profile and shows a packs failure", async () => {
  server.use(
    http.get("*/api/packs", () =>
      HttpResponse.json({ detail: "packs unavailable" }, { status: 404 }),
    ),
  );
  const { user } = renderWithClient(<Host />);
  expect(await screen.findByRole("alert")).toHaveTextContent("packs unavailable");
  const profile = screen.getByRole("combobox", { name: "Team profile" });
  await user.selectOptions(profile, "");
  expect(profile).toHaveValue("");
});

it("puts a profile that is a draft now back to the default, opens the fold and says so (CRL-108)", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  const { user } = renderWithClient(<Host initial="draft-west" />);
  const note = await screen.findByText(
    "Team profile “draft-west” is no longer available, so no team profile is used.",
  );
  const profile = screen.getByRole("combobox", { name: "Team profile" });
  expect(profile).toHaveValue("");
  expect(note.closest("details")).toHaveAttribute("open");
  await user.selectOptions(profile, "team-east");
  expect(profile).toHaveValue("team-east");
  expect(screen.queryByText(/no longer available/)).toBeNull(); // a choice clears the note
});

it("keeps a profile that can be chosen, and any profile while the packs cannot be read (CRL-108)", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  renderWithClient(<Host initial="team-east" />);
  await screen.findByRole("option", { name: "team-east" });
  expect(screen.getByRole("combobox", { name: "Team profile" })).toHaveValue("team-east");
  expect(screen.queryByText(/no longer available/)).toBeNull();
  cleanup();
  const onProfile = vi.fn();
  server.use(
    http.get("*/api/packs", () =>
      HttpResponse.json({ detail: "packs unavailable" }, { status: 500 }),
    ),
  );
  renderWithClient(
    <RunOptions
      profile="team-east"
      onProfile={onProfile}
      guidance=""
      onGuidance={() => {}}
      maxIterations={2}
      onMaxIterations={() => {}}
    />,
  );
  await screen.findByRole("alert");
  expect(onProfile).not.toHaveBeenCalled();
  expect(screen.queryByText(/no longer available/)).toBeNull();
});

it("names the deployment's default in the note when it has one (CRL-108)", async () => {
  server.use(
    http.get("*/api/packs", () => HttpResponse.json(packs)),
    http.get("*/api/system/info", () =>
      HttpResponse.json({ ...info, default_profile: "team-east" }),
    ),
  );
  renderWithClient(<Host initial="retired" />);
  expect(
    await screen.findByText(
      "Team profile “retired” is no longer available, so the default is used.",
    ),
  ).toBeInTheDocument();
});

it("holds the check while the page may still replace the profile (CRL-108)", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  const onProfile = vi.fn();
  function Pending() {
    const [settled, setSettled] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setSettled(true)}>
          Settle
        </button>
        <RunOptions
          profile="retired"
          onProfile={onProfile}
          guidance=""
          onGuidance={() => {}}
          maxIterations={2}
          onMaxIterations={() => {}}
          settled={settled}
        />
      </>
    );
  }
  const { user } = renderWithClient(<Pending />);
  await screen.findByRole("option", { name: "team-east" });
  expect(onProfile).not.toHaveBeenCalled();
  expect(screen.queryByText(/no longer available/)).toBeNull();
  await user.click(screen.getByRole("button", { name: "Settle" }));
  await waitFor(() => expect(onProfile).toHaveBeenCalledWith(null));
});

it("offers Guidance for the writer in the fold, bounded at the API's 8,000 characters with a count (CRL-132)", async () => {
  server.use(http.get("*/api/packs", () => HttpResponse.json(packs)));
  const { user } = renderWithClient(<Host />);
  const fold = screen.getByText("More options").closest("details")!;
  const box = screen.getByRole("textbox", { name: "Guidance for the writer" });
  expect(fold).toContainElement(box);
  expect(box).toHaveAttribute("maxLength", "8000");
  await user.type(box, "Lead with capacity");
  expect(box).toHaveValue("Lead with capacity");
  expect(screen.queryByText(/of 8,000 characters/)).toBeNull();
  fireEvent.change(box, { target: { value: "g".repeat(7200) } });
  expect(box).toHaveAccessibleDescription("7,200 of 8,000 characters");
});
