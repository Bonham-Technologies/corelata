import { http, HttpResponse } from "msw";
import {
  ApiError,
  client,
  errorText,
  eventsUrl,
  exportUrl,
  isNotFound,
  NETWORK_ERROR,
  reportUrl,
  unwrap,
  unwrapText,
} from "./client";
import { deferred } from "../test/deferred";
import { server } from "../test/server";

describe("errorText", () => {
  it("prefers the API's one-line detail", () => {
    expect(errorText(409, { detail: "run 1 is already cancelled" })).toBe(
      "run 1 is already cancelled",
    );
  });
  it("names the field of a validation error without its location prefix", () => {
    const body = { detail: [{ loc: ["body", "value_statement"], msg: "String too short" }] };
    expect(errorText(422, body)).toBe("value_statement: String too short");
    expect(errorText(422, { detail: [{ msg: "bad" }] })).toBe("bad");
  });
  it("falls back to the status", () => {
    expect(errorText(502, null)).toBe("The server answered 502 without an explanation.");
    expect(errorText(500, { detail: "" })).toBe("The server answered 500 without an explanation.");
  });
});

describe("isNotFound (CRL-130)", () => {
  const id = "00000000-0000-0000-0000-000000000001";
  it("is a 404, or a 422 for an id from the address that is not a UUID", () => {
    expect(isNotFound(new ApiError(404, "run x not found"))).toBe(true);
    expect(isNotFound(new ApiError(422, "run_id: Input should be a valid UUID"), "0000")).toBe(
      true,
    );
  });
  it("is nothing else: another status, a 422 for a well-formed id, or not an API error", () => {
    expect(isNotFound(new ApiError(503, "the database is unavailable"), "0000")).toBe(false);
    expect(isNotFound(new ApiError(422, "statement: too long"), id)).toBe(false);
    expect(isNotFound(new ApiError(422, "statement: too long"))).toBe(false);
    expect(isNotFound(new ApiError(0, NETWORK_ERROR), "0000")).toBe(false);
    expect(isNotFound(new Error("not found"), "0000")).toBe(false);
    expect(isNotFound(undefined)).toBe(false);
  });
});

describe("unwrap", () => {
  it("returns the data of a 2xx", async () => {
    server.use(http.get("*/api/projects", () => HttpResponse.json([{ id: "p" }])));
    await expect(unwrap(client.GET("/api/projects"))).resolves.toEqual([{ id: "p" }]);
  });
  it("throws an ApiError with the detail of a 4xx", async () => {
    server.use(
      http.get("*/api/projects", () => HttpResponse.json({ detail: "nope" }, { status: 404 })),
    );
    const error = await unwrap(client.GET("/api/projects")).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, message: "nope" });
  });
  it("turns a network failure into a readable error", async () => {
    server.use(http.get("*/api/projects", () => HttpResponse.error()));
    await expect(unwrap(client.GET("/api/projects"))).rejects.toMatchObject({
      status: 0,
      message: NETWORK_ERROR,
    });
  });
});

describe("unwrapText", () => {
  it("returns the body text and maps failures like unwrap", async () => {
    server.use(http.get("*/api/runs/r/report", () => HttpResponse.text("<html>x</html>")));
    await expect(unwrapText("/api/runs/r/report")).resolves.toBe("<html>x</html>");
    server.use(
      http.get("*/api/runs/r/report", () =>
        HttpResponse.json({ detail: "run r has no report (state failed)" }, { status: 409 }),
      ),
    );
    await expect(unwrapText("/api/runs/r/report")).rejects.toMatchObject({
      status: 409,
      message: "run r has no report (state failed)",
    });
    server.use(http.get("*/api/runs/r/report", () => new HttpResponse("boom", { status: 500 })));
    await expect(unwrapText("/api/runs/r/report")).rejects.toMatchObject({ status: 500 });
    server.use(http.get("*/api/runs/r/report", () => HttpResponse.error()));
    await expect(unwrapText("/api/runs/r/report")).rejects.toMatchObject({ status: 0 });
  });
});

describe("a cancelled request (CRL-40)", () => {
  function held(path: string) {
    const gate = deferred();
    server.use(
      http.get(path, async () => {
        await gate.promise;
        return HttpResponse.json([]);
      }),
    );
    return gate;
  }

  it("rejects with its AbortError, not the network error", async () => {
    const gate = held("*/api/projects");
    const controller = new AbortController();
    const call = unwrap(client.GET("/api/projects", { signal: controller.signal }));
    controller.abort();
    const error = await call.catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ name: "AbortError" });
    gate.resolve();
  });

  it("does the same for a text route", async () => {
    const gate = held("*/api/runs/r/report");
    const controller = new AbortController();
    const call = unwrapText("/api/runs/r/report", controller.signal);
    controller.abort();
    await expect(call).rejects.toMatchObject({ name: "AbortError" });
    gate.resolve();
  });
});

describe("urls", () => {
  it("builds the browser-loaded URLs", () => {
    expect(eventsUrl("r 1")).toBe("/api/runs/r%201/events");
    expect(reportUrl("r", "html")).toBe("/api/runs/r/report?format=html");
    expect(reportUrl("r", "html", { claimIds: true })).toBe(
      "/api/runs/r/report?format=html&with_claim_ids=true",
    );
    expect(reportUrl("r", "docx", { download: true })).toBe(
      "/api/runs/r/report?format=docx&download=true",
    );
    expect(exportUrl("r", "trace.json")).toBe("/api/runs/r/exports/trace.json");
  });
});
