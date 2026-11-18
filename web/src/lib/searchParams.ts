import { createContext, useCallback, useContext, useLayoutEffect, useRef } from "react";
import { type NavigateOptions, useSearchParams } from "react-router";

/** A change to the page's search parameters: a copy of the parameters as they are now in (it may
 * change and return it), the new ones out, or null to leave them as they are. */
export type SearchParamsChange = (now: URLSearchParams) => URLSearchParams | null;
export type UpdateSearchParams = (change: SearchParamsChange, options?: NavigateOptions) => void;

/** The search parameters, and a writer whose changes compose (CRL-62). React Router's own
 * functional `setSearchParams` hands its function the parameters of the render it was made in,
 * not the URL as it is now, so two writes before the next render (an upload finishing as the
 * analyst ticks a source) lose the first. This writer applies each change to the URL as the
 * last write left it, and follows the URL when it changes otherwise (a link, Back). */
export function useSearchParamsWriter(): [URLSearchParams, UpdateSearchParams] {
  const [params, setParams] = useSearchParams();
  const latest = useRef({ params, setParams });
  const rendered = useRef(params.toString());
  // what this writer navigated to that the page has not rendered yet, oldest first
  const unrendered = useRef<string[]>([]);
  // a layout effect: it runs in the commit, so a click always meets `latest` and the page agree
  useLayoutEffect(() => {
    const now = params.toString();
    // a render before our own navigation lands (a refetch finishing) still holds the old
    // parameters and must not undo what was written here
    if (now === rendered.current) return;
    rendered.current = now;
    const own = unrendered.current.indexOf(now);
    if (own >= 0) {
      // one of our writes landing, perhaps before a later one: `latest` holds that later one
      unrendered.current.splice(0, own + 1);
      latest.current = { params: latest.current.params, setParams };
      return;
    }
    unrendered.current = []; // the URL changed otherwise (a link, Back)
    latest.current = { params, setParams };
  }, [params, setParams]);
  const update = useCallback<UpdateSearchParams>((change, options) => {
    const { params: now, setParams: set } = latest.current;
    const next = change(new URLSearchParams(now));
    if (next === null || next.toString() === now.toString()) return;
    latest.current = { params: next, setParams: set };
    unrendered.current.push(next.toString());
    set(next, options);
  }, []);
  return [params, update];
}

const Shared = createContext<UpdateSearchParams | null>(null);

/** A page whose parts write its search parameters gives them its one writer, so every part's
 * change applies to what the others wrote. */
export const SearchParamsWriterProvider = Shared.Provider;

/** The page's shared writer, or one of the component's own outside such a page. */
export function useUpdateSearchParams(): UpdateSearchParams {
  const shared = useContext(Shared);
  const [, own] = useSearchParamsWriter();
  return shared ?? own;
}
