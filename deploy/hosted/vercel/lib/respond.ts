/** Turns a routing Decision into the front door's response. Every response carries X-Robots-Tag:
 * the demo is a private sign-in page and must stay out of search results (CRL-98). */
import { next, rewrite } from "@vercel/functions";
import type { Decision } from "./route.js"; // Node ESM needs the extension at run time

export const ROBOTS_TAG = "noindex, nofollow";
const NOINDEX = { "x-robots-tag": ROBOTS_TAG };

export function respond(d: Decision): Response {
  switch (d.kind) {
    case "next":
      return next({ headers: NOINDEX });
    case "redirect": {
      const headers = new Headers({ location: d.location, ...NOINDEX });
      if (d.setCookie) headers.set("set-cookie", d.setCookie);
      return new Response(null, { status: 303, headers });
    }
    case "unauthorized":
      return Response.json({ detail: "signed out: sign in again" }, { status: 401, headers: NOINDEX });
    case "misconfigured":
      return new Response("The Corelata demo is not configured.", { status: 503, headers: NOINDEX });
    case "forbidden":
      return new Response("Cross-site request refused.", { status: 403, headers: NOINDEX });
    case "forward":
      return rewrite(d.url, { request: { headers: d.headers }, headers: NOINDEX });
  }
}
