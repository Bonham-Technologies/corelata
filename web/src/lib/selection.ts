/** The chosen sources in the new-report URL, short enough for any proxy (CRL-54).
 *
 * `pick=i.<token>.<token>` names the chosen sources and `pick=x.<token>.<token>` the ones left
 * out; the page writes whichever list is shorter, so the worst case is half the project's
 * sources. A token is 6 URL-safe characters (36 bits of a hash of the source id), so 500
 * sources half chosen take about 1.75 kB where their ids took 9 kB. Two of a project's sources
 * share a token about once in 500 000 projects of 500 sources; they are then chosen together.
 *
 * `x` keeps a source added after the URL was written (another tab, a colleague) chosen, as
 * every source is when there is no parameter at all; `i` leaves it out, as the old id list did.
 * Links written before CRL-54 carry `sources=<id>,<id>` and still load. */
export const SELECTION_PARAM = "pick";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const TOKEN_LENGTH = 6; // 6 × 6 bits = 36 bits
const SEPARATOR = "."; // unreserved: URLSearchParams leaves it as it is, unlike ","

/** cyrb53 (public domain): a fast 53-bit string hash with good spread. */
function hash53(text: string): number {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
  h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
  h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return 4294967296 * (2097151 & h2) + (h1 >>> 0);
}

/** A source id's token in the URL. */
export function sourceToken(id: string): string {
  let n = hash53(id);
  let token = "";
  for (let i = 0; i < TOKEN_LENGTH; i++) {
    token += ALPHABET[n % 64];
    n = Math.floor(n / 64);
  }
  return token;
}

/** The parameter's value for `chosen` out of the project's sources `all`. */
export function encodeSelection(all: readonly string[], chosen: ReadonlySet<string>): string {
  const picked = all.filter((id) => chosen.has(id));
  const left = all.filter((id) => !chosen.has(id));
  const [mode, ids] = picked.length <= left.length ? ["i", picked] : ["x", left];
  return [mode, ...ids.map(sourceToken)].join(SEPARATOR);
}

/** The project's sources `all` that the parameter's value chooses. A value this page did not
 * write chooses none, as an old link naming no source of the project does. */
export function decodeSelection(value: string, all: readonly string[]): Set<string> {
  const [mode, ...tokens] = value.split(SEPARATOR);
  if (mode !== "i" && mode !== "x") return new Set();
  const named = new Set(tokens);
  return new Set(all.filter((id) => named.has(sourceToken(id)) === (mode === "i")));
}

/** The value with `added` chosen too, for sources the project did not have when it was written.
 * An `x` value chooses them already. */
export function withAdded(value: string, added: readonly string[]): string {
  const [mode, ...tokens] = value.split(SEPARATOR);
  if (mode === "x") return value;
  const kept = mode === "i" ? tokens : []; // a value this page did not write chose none
  return ["i", ...new Set([...kept, ...added.map(sourceToken)])].join(SEPARATOR);
}
