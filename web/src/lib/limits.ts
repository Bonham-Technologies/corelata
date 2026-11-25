/** The API's length limits on free text (CRL-83), from its request models in
 * api/corelata_api/routes. limits.test.ts checks them against schema/openapi.json. */
export const VALUE_STATEMENT_MAX_LENGTH = 4000;
export const NOTE_MAX_LENGTH = 8000;
/** The writer guidance a run starts with (`CreateRun.extra_guidance`, CRL-132). */
export const GUIDANCE_MAX_LENGTH = 8000;

/** A count shows from this share of the limit on, so it says nothing while there is room. */
export const COUNT_FROM = 0.9;
