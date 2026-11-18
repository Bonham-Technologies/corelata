import { respond } from "./lib/respond.js"; // Node ESM needs the extension at run time
import { decide, readEnv } from "./lib/route.js";

export const config = { runtime: "nodejs" };

export default async function middleware(request: Request): Promise<Response> {
  return respond(await decide(request, readEnv(), Date.now()));
}
