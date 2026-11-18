import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { server } from "./server";

configure({ asyncUtilTimeout: 5000 });

// jsdom has no HTMLDialogElement.showModal/close: provide the minimum the components use. A test
// file in the node environment (fonts.test.ts) has no DOM at all.
if (typeof HTMLDialogElement !== "undefined") {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.open = false;
  };
}

// msw's "error" strategy only prints the request and fails that fetch; the component under test
// shows a network error and the test still passes. Record every unhandled request and fail the
// test it happened in (or, after the file's last test, the file) instead (CRL-37).
const unhandled: string[] = [];

function failOnUnhandled(when: string) {
  const seen = unhandled.splice(0);
  if (seen.length > 0) {
    throw new Error(`unhandled request(s) ${when}: ${seen.join(", ")}; mock them with server.use`);
  }
}

beforeAll(() =>
  server.listen({
    onUnhandledRequest: (request, print) => {
      unhandled.push(`${request.method} ${new URL(request.url).pathname}`);
      print.error();
    },
  }),
);
afterEach(() => {
  cleanup();
  // a draft one test leaves (CRL-74) must not show up in the next test's page
  if (typeof sessionStorage !== "undefined") sessionStorage.clear();
  server.resetHandlers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  failOnUnhandled("in this test");
});
afterAll(() => {
  server.close();
  failOnUnhandled("after the last test of this file");
});
