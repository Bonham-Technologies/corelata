import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { makeQueryClient, Providers } from "../Providers";
import { packs, resolvedPack } from "../test/fixtures";
import { server } from "../test/server";
import { RESOLVED_PACK_STALE_MS, usePacks, useResolvedPack } from "./packs";

function wrapper({ children }: { children: ReactNode }) {
  return <Providers client={makeQueryClient({ retry: false })}>{children}</Providers>;
}

it("lists packs and resolves one with a profile", async () => {
  server.use(
    http.get("*/api/packs", () => HttpResponse.json(packs)),
    http.get("*/api/packs/icd203-base/resolved", ({ request }) => {
      expect(new URL(request.url).searchParams.get("profile")).toBe("team-east");
      return HttpResponse.json({ ...resolvedPack, profile: "team-east" });
    }),
  );
  const list = renderHook(() => usePacks(), { wrapper });
  await waitFor(() => expect(list.result.current.data).toEqual(packs));
  const resolved = renderHook(() => useResolvedPack("icd203-base", "team-east"), { wrapper });
  await waitFor(() => expect(resolved.result.current.data?.profile).toBe("team-east"));
  expect(
    renderHook(() => useResolvedPack(null, null), { wrapper }).result.current.fetchStatus,
  ).toBe("idle");
});

it("resolves a pack without a profile", async () => {
  server.use(
    http.get("*/api/packs/icd203-base/resolved", ({ request }) => {
      expect(new URL(request.url).searchParams.has("profile")).toBe(false);
      return HttpResponse.json(resolvedPack);
    }),
  );
  const resolved = renderHook(() => useResolvedPack("icd203-base", null), { wrapper });
  await waitFor(() => expect(resolved.result.current.data?.profile).toBeNull());
});

it("keeps a resolved pack fresh for ten minutes (the Audit tab opens often)", async () => {
  server.use(http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)));
  const client = makeQueryClient({ retry: false });
  const resolved = renderHook(() => useResolvedPack("icd203-base", null), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  await waitFor(() => expect(resolved.result.current.data).toBeTruthy());
  const query = client
    .getQueryCache()
    .find({ queryKey: ["packs", "icd203-base", "resolved", null] })!;
  expect(query.observers[0]!.options.staleTime).toBe(RESOLVED_PACK_STALE_MS);
  expect(RESOLVED_PACK_STALE_MS).toBe(10 * 60_000);
});
