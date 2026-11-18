import { ApiError } from "./api/client";
import { makeQueryClient, retryOnce } from "./Providers";

it("retries once on a network error or a 5xx and never on a 4xx", () => {
  expect(retryOnce(0, new ApiError(0, "down"))).toBe(true);
  expect(retryOnce(1, new ApiError(0, "down"))).toBe(false);
  expect(retryOnce(0, new ApiError(503, "down"))).toBe(true);
  expect(retryOnce(0, new ApiError(404, "gone"))).toBe(false);
  expect(retryOnce(0, new Error("x"))).toBe(true);
});

it("builds a client with the retry policy, or none for tests", () => {
  expect(makeQueryClient().getDefaultOptions().queries?.retry).toBe(retryOnce);
  expect(makeQueryClient({ retry: false }).getDefaultOptions().queries?.retry).toBe(false);
});
