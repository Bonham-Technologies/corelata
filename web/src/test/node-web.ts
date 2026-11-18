// jsdom brings its own FormData and File, which Node's fetch cannot read. The upload test
// swaps in Node's classes with vi.stubGlobal; nothing else needs them.
import { File as NodeFile } from "node:buffer";

export async function nodeFormData(): Promise<typeof FormData> {
  const parsed = await new Response("a=1", {
    headers: { "content-type": "application/x-www-form-urlencoded" },
  }).formData();
  return parsed.constructor as typeof FormData;
}

export const NodeFileClass = NodeFile as unknown as typeof File;
