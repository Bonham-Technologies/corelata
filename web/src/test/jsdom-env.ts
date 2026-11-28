import { builtinEnvironments, type Environment } from "vitest/runtime";
import { pointStorageAtJsdom } from "./jsdom-storage";

// jsdom's AbortController breaks react-router's Node `Request`; keep Node's. Node 25 and later
// define their own (empty) localStorage, which hides jsdom's; the theme tests need jsdom's
// (copied from Coglossa, spec §2.2).
const env: Environment = {
  ...builtinEnvironments.jsdom,
  name: "jsdom-node-abort",
  async setup(global, options) {
    const NodeAbortController = global.AbortController;
    const result = await builtinEnvironments.jsdom.setup(global, options);
    global.AbortController = NodeAbortController;
    pointStorageAtJsdom(global);
    return result;
  },
};
export default env;
