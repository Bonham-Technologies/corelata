import { renderHook } from "@testing-library/react";
import { useSearchParamsWriter } from "./searchParams";

const router = vi.hoisted(() => ({
  params: new URLSearchParams(),
  set: vi.fn<(next: URLSearchParams, options?: unknown) => void>(),
}));

vi.mock("react-router", () => ({
  useSearchParams: () => [router.params, router.set],
}));

const add = (key: string) => (now: URLSearchParams) => {
  now.set(key, "1");
  return now;
};
const lastWrite = () => router.set.mock.lastCall?.[0].toString();

beforeEach(() => {
  router.params = new URLSearchParams();
  router.set.mockClear();
});

it("keeps a later write when an earlier one of its own renders first (CRL-62)", () => {
  const { result, rerender } = renderHook(() => useSearchParamsWriter());
  result.current[1](add("a"));
  result.current[1](add("b"));
  router.params = new URLSearchParams("a=1"); // the first write commits; the second has not
  rerender();
  result.current[1](add("c"));
  expect(lastWrite()).toBe("a=1&b=1&c=1");
  router.params = new URLSearchParams("a=1&b=1&c=1"); // the last one lands
  rerender();
  result.current[1](add("d"));
  expect(lastWrite()).toBe("a=1&b=1&c=1&d=1");
});

it("follows the URL when it changes otherwise, and writes nothing for no change", () => {
  const { result, rerender } = renderHook(() => useSearchParamsWriter());
  result.current[1](add("a"));
  router.params = new URLSearchParams("project=p"); // a link, Back: not one of its writes
  rerender();
  result.current[1](add("b"));
  expect(lastWrite()).toBe("project=p&b=1");
  router.set.mockClear();
  result.current[1](() => null);
  result.current[1]((now) => now);
  expect(router.set).not.toHaveBeenCalled();
});
