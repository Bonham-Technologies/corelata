import { useEffect, useId, useRef, useState } from "react";
import { usePacks } from "../../api/packs";
import { useInfo } from "../../api/system";
import { ErrorMessage } from "../../components/ErrorMessage";

/** Revision rounds as typed: a whole number within 0-10, or null for an empty field (the
 * deployment's pipeline.max_iterations, CRL-67). */
export function roundsOf(text: string): number | null {
  const n = Number(text);
  if (text.trim() === "" || !Number.isFinite(n)) return null;
  return Math.min(10, Math.max(0, Math.round(n)));
}

/** The project page's More options fold, closed (M18 spec §5.2): the team profile and the
 * revision rounds, as before M18. The rounds field keeps what is typed while it has focus and
 * shows the value the page holds once it is left, so retyping never passes through 0 and an
 * emptied field goes back to the deployment's rounds (CRL-90). A profile from a draft or an
 * earlier run that the default pack no longer offers enabled (removed, or a draft now) goes back
 * to the default once the packs are read, and the fold opens to say so: the select could not
 * show it, and the run would be refused (CRL-108). `settled` false holds that check while the
 * page may still replace the profile (a link from an earlier run that is loading), so it runs
 * once, on the profile the page ends with. */
export function RunOptions({
  profile,
  onProfile,
  maxIterations,
  onMaxIterations,
  settled = true,
}: {
  profile: string | null;
  onProfile: (profile: string | null) => void;
  maxIterations: number;
  /** A whole number within 0-10, or null to follow the deployment. */
  onMaxIterations: (n: number | null) => void;
  /** false while the page may still replace the profile. */
  settled?: boolean;
}) {
  const info = useInfo();
  const packs = usePacks();
  const pack = (packs.data ?? []).find((p) => p.name === info.data?.default_pack);
  const profileId = useId();
  const roundsId = useId();
  const [typed, setTyped] = useState<string | null>(null); // null: show maxIterations
  const offered = pack?.profiles ?? [];
  const usable = profile === null || offered.some((p) => p.name === profile && !p.draft);
  // only once both are read: without them nothing says the profile is gone
  const stale = settled && packs.data && info.data && !usable ? profile : null;
  const [dropped, setDropped] = useState<string | null>(null);
  if (stale !== null && dropped !== stale) setDropped(stale);
  const fold = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (stale === null) return;
    fold.current!.open = true; // the note is in the fold
    onProfile(null);
  }, [stale, onProfile]);
  return (
    <details ref={fold} className="card options">
      <summary>More options</summary>
      <div className="row">
        <div className="field">
          <label htmlFor={profileId}>Team profile</label>
          <select
            id={profileId}
            value={profile ?? ""}
            onChange={(e) => {
              setDropped(null);
              onProfile(e.target.value || null);
            }}
          >
            <option value="">
              {info.data?.default_profile
                ? `Default (${info.data.default_profile})`
                : "No team profile"}
            </option>
            {offered.map((p) => (
              <option key={p.name} value={p.name} disabled={p.draft}>
                {p.name}
                {p.draft ? " (draft)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor={roundsId}>Revision rounds</label>
          <input
            id={roundsId}
            type="number"
            min={0}
            max={10}
            value={typed ?? maxIterations}
            onChange={(e) => {
              setTyped(e.target.value);
              onMaxIterations(roundsOf(e.target.value));
            }}
            onBlur={() => setTyped(null)}
          />
        </div>
      </div>
      {dropped !== null ? (
        <p className="muted">
          Team profile “{dropped}” is no longer available, so{" "}
          {info.data?.default_profile ? "the default is used" : "no team profile is used"}.
        </p>
      ) : null}
      {packs.error ? <ErrorMessage error={packs.error} /> : null}
    </details>
  );
}
