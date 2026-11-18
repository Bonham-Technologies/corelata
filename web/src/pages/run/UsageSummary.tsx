import type { Usage } from "../../api/types";
import { formatInt } from "../../lib/format";

export function UsageSummary({ usage }: { usage: Usage | null | undefined }) {
  if (!usage) return null;
  return (
    <p role="status" aria-label="Token usage" className="muted">
      {formatInt(usage.calls)} model call{usage.calls === 1 ? "" : "s"} ·{" "}
      {formatInt(usage.tokens_in)} in · {formatInt(usage.tokens_out)} out
    </p>
  );
}
