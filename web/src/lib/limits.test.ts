// @vitest-environment node
import { readFileSync } from "node:fs";
import { NOTE_MAX_LENGTH, VALUE_STATEMENT_MAX_LENGTH } from "./limits";

const openapi = JSON.parse(
  readFileSync(new URL("../../../schema/openapi.json", import.meta.url), "utf8"),
) as {
  components: { schemas: Record<string, { properties: Record<string, { maxLength?: number }> }> };
};
const maxLength = (schema: string, field: string) =>
  openapi.components.schemas[schema]?.properties[field]?.maxLength;

it("matches the API's limits in schema/openapi.json (CRL-83)", () => {
  expect(maxLength("CreateRun", "value_statement")).toBe(VALUE_STATEMENT_MAX_LENGTH);
  expect(maxLength("ReviewRequest", "note")).toBe(NOTE_MAX_LENGTH);
});
