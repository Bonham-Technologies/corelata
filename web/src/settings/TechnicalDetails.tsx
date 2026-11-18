import { usePacks } from "../api/packs";
import { useInfo } from "../api/system";
import type { DoctorReport } from "../api/types";
import { ErrorMessage } from "../components/ErrorMessage";
import { Loading } from "../components/Loading";

function Checks({ report }: { report: DoctorReport | undefined }) {
  if (report === undefined) return null;
  return (
    <table aria-label="Checks">
      <thead>
        <tr>
          <th>Result</th>
          <th>Check</th>
          <th>Details</th>
          <th>What to do</th>
        </tr>
      </thead>
      <tbody>
        {report.checks.map((check, i) => (
          <tr key={`${check.name}-${i}`}>
            <td>{check.status}</td>
            <td>{check.name}</td>
            <td dir="auto">{check.message}</td>
            <td dir="auto">{check.fix}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Packs() {
  const packs = usePacks();
  if (packs.isPending) return <Loading what="Loading the standards packs" />;
  if (packs.isError) return <ErrorMessage error={packs.error} />;
  return (
    <ul aria-label="Standards packs">
      {packs.data.map((pack) => (
        <li key={pack.name}>
          {pack.name} {pack.version}
          {pack.error ? <span className="error"> {pack.error}</span> : null}
          {pack.profiles.length > 0 ? (
            <>
              {": "}
              {pack.profiles.map((p) => `${p.name}${p.draft ? " (draft)" : ""}`).join(", ")}
            </>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Settings ▸ Technical details (M18 spec §5.6), folded: what an administrator asks for. */
export function TechnicalDetails({ report }: { report: DoctorReport | undefined }) {
  const info = useInfo();
  return (
    <details className="technical">
      <summary>Technical details</summary>
      {info.data ? (
        <dl className="facts">
          <dt>Version</dt>
          <dd>{info.data.version}</dd>
          <dt>Sign-in</dt>
          <dd>
            {info.data.auth_mode === "none"
              ? "none (auth.mode none)"
              : "by the proxy (trusted_header)"}
          </dd>
          <dt>Upload limit</dt>
          <dd>{info.data.max_upload_mb} MB</dd>
          <dt>Default standards pack</dt>
          <dd>{info.data.default_pack}</dd>
          <dt>Default team profile</dt>
          <dd>{info.data.default_profile ?? "none"}</dd>
        </dl>
      ) : null}
      <h3>Standards packs and team profiles</h3>
      <Packs />
      <h3>Installation checks</h3>
      <Checks report={report} />
    </details>
  );
}
