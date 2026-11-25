import { clearAllDrafts, clearDraft, draftKey, EMPTY_DRAFT, loadDraft, saveDraft } from "./draft";

const ID = "p1";

it("saves, loads and clears a project's draft under corelata.draft.<id>", () => {
  const draft = { statement: "Varna", profile: "team-east", maxIterations: 1, guidance: "Lead" };
  saveDraft(ID, draft);
  expect(draftKey(ID)).toBe("corelata.draft.p1");
  expect(JSON.parse(sessionStorage.getItem("corelata.draft.p1") ?? "null")).toEqual(draft);
  expect(loadDraft(ID)).toEqual(draft);
  expect(loadDraft("p2")).toEqual(EMPTY_DRAFT);
  clearDraft(ID);
  expect(sessionStorage.getItem("corelata.draft.p1")).toBeNull();
});

it("removes the entry when nothing is written", () => {
  saveDraft(ID, { statement: "x", profile: null, maxIterations: null, guidance: "" });
  saveDraft(ID, EMPTY_DRAFT);
  expect(sessionStorage.getItem(draftKey(ID))).toBeNull();
});

it.each([
  ["not JSON", "{", EMPTY_DRAFT],
  ["null", "null", EMPTY_DRAFT],
  ["a string", '"x"', EMPTY_DRAFT],
  [
    "wrong field types",
    '{"statement":1,"profile":2,"maxIterations":"3","guidance":4}',
    EMPTY_DRAFT,
  ],
  [
    "a draft saved before guidance",
    '{"statement":"s","profile":null,"maxIterations":1}',
    { ...EMPTY_DRAFT, statement: "s", maxIterations: 1 },
  ],
  ["guidance alone", '{"guidance":"Lead"}', { ...EMPTY_DRAFT, guidance: "Lead" }],
  [
    "rounds that are not a whole number from 0",
    '{"statement":"s","maxIterations":1.5}',
    { ...EMPTY_DRAFT, statement: "s" },
  ],
  ["negative rounds", '{"maxIterations":-1}', EMPTY_DRAFT],
  [
    "rounds over the field's maximum",
    '{"maxIterations":99}',
    { ...EMPTY_DRAFT, maxIterations: 10 },
  ],
])("reads %s as what it can", (_, raw, expected) => {
  sessionStorage.setItem(draftKey(ID), raw);
  expect(loadDraft(ID)).toEqual(expected);
});

it("ignores storage that throws", () => {
  sessionStorage.setItem(draftKey(ID), "{}"); // so clearAllDrafts has a key to read
  for (const method of ["getItem", "setItem", "removeItem"] as const) {
    vi.spyOn(Storage.prototype, method).mockImplementation(() => {
      throw new Error("blocked");
    });
  }
  expect(loadDraft(ID)).toEqual(EMPTY_DRAFT);
  expect(() => saveDraft(ID, { ...EMPTY_DRAFT, statement: "x" })).not.toThrow();
  expect(() => saveDraft(ID, EMPTY_DRAFT)).not.toThrow();
  expect(() => clearDraft(ID)).not.toThrow();
  vi.spyOn(Storage.prototype, "key").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(() => clearAllDrafts()).not.toThrow();
});
