import { render } from "@testing-library/react";
import { ActiveProjectContext, useActiveProject, useDocumentTitle } from "./frame";

function Page({ project, title }: { project: string | null; title: string | null }) {
  useActiveProject(project);
  useDocumentTitle(title);
  return null;
}

it("names the page's project to the frame while it is on screen, and sets the tab's title", () => {
  const seen: (string | null)[] = [];
  const set = (id: string | null) => seen.push(id);
  document.title = "Corelata";
  const { rerender, unmount } = render(
    <ActiveProjectContext.Provider value={set}>
      <Page project="p1" title={null} />
    </ActiveProjectContext.Provider>,
  );
  expect(document.title).toBe("Corelata"); // null: still loading, left alone
  rerender(
    <ActiveProjectContext.Provider value={set}>
      <Page project="p2" title="Black Sea – Corelata" />
    </ActiveProjectContext.Provider>,
  );
  expect(document.title).toBe("Black Sea – Corelata");
  unmount();
  expect(seen).toEqual(["p1", null, "p2", null]);
});

it("does nothing outside a frame", () => {
  expect(() => render(<Page project="p1" title={null} />)).not.toThrow();
});
