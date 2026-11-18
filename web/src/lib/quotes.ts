/** Where a claim's quote sits in its unit (CRL-93), for the Claims tab's highlight.
 *
 * Like the engine's check (`corelata/quotes.py`), a quote and a unit are compared as words:
 * case, whitespace, quote marks and other punctuation never decide a match. The engine also
 * NFKC-normalises and, below `pipeline.quote_match_threshold` 1.0, matches fuzzily, so a quote
 * it accepted can still be one the browser does not find; the tab then shows the whole unit, as
 * it did before quotes existed. */

export type Span = readonly [start: number, end: number];

const WORD = /[\p{L}\p{N}\p{M}_]+/gu;

interface Word {
  text: string;
  start: number;
  end: number;
}

function words(text: string): Word[] {
  return Array.from(text.matchAll(WORD), (m) => ({
    text: m[0].toLowerCase(),
    start: m.index,
    end: m.index + m[0].length,
  }));
}

/** The span of `text` holding the quote's words as one run, or null when it is not there. */
export function findQuote(text: string, quote: string): Span | null {
  const want = words(quote).map((w) => w.text);
  if (want.length === 0) return null;
  const have = words(text);
  for (let i = 0; i + want.length <= have.length; i++) {
    if (want.every((w, k) => have[i + k]!.text === w)) {
      return [have[i]!.start, have[i + want.length - 1]!.end];
    }
  }
  return null;
}

/** The spans of every quote found in `text`, sorted, with overlapping or touching spans joined. */
export function quoteSpans(text: string, quotes: readonly string[]): Span[] {
  const found = quotes
    .map((q) => findQuote(text, q))
    .filter((s): s is Span => s !== null)
    .sort((a, b) => a[0] - b[0]);
  const out: [number, number][] = [];
  for (const [start, end] of found) {
    const last = out.at(-1);
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else out.push([start, end]);
  }
  return out;
}
