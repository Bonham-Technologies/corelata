import { useDoctor, useDoctorStatus } from "../api/system";
import type { DoctorReport } from "../api/types";
import { ErrorMessage } from "../components/ErrorMessage";
import { useDocumentTitle } from "../components/frame";
import { Loading } from "../components/Loading";
import { useTheme, type ThemeChoice } from "../theme/theme";
import { reportFailed, statusSentence } from "./statusSentence";
import { TechnicalDetails } from "./TechnicalDetails";

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Match my computer" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

/** Adapted from Coglossa's SettingsPage: a card with a heading, like Status (M18 polish F4). */
function Appearance() {
  const { choice, setChoice } = useTheme();
  return (
    <section aria-label="Appearance" className="card appearance">
      <h2>Appearance</h2>
      <div role="radiogroup" aria-label="Theme">
        {THEMES.map((t) => (
          <label key={t.value}>
            <input
              type="radio"
              name="theme"
              value={t.value}
              checked={choice === t.value}
              onChange={() => setChoice(t.value)}
            />{" "}
            {t.label}
          </label>
        ))}
      </div>
    </section>
  );
}

function Sentence({ report }: { report: DoctorReport }) {
  const failed = reportFailed(report);
  return (
    <p className={failed ? "tone-bad" : "tone-ok"}>
      <span aria-hidden="true">{failed ? "! " : "✓ "}</span>
      {statusSentence(report)}
    </p>
  );
}

/** M18 spec §5.6: Appearance, Status and Technical details, for everyone (Corelata has no
 * roles). The quick check (no test completions) runs when the page opens; the full one when
 * asked, and only its sentence is announced. */
export function SettingsPage() {
  useDocumentTitle("Settings – Corelata");
  const quick = useDoctorStatus();
  const full = useDoctor();
  const report = full.data ?? quick.data; // the newest check wins, in the sentence and the table
  return (
    <section className="settings">
      <h1>Settings</h1>
      <Appearance />
      <section aria-label="Status" className="card">
        <h2>Status</h2>
        {report === undefined && quick.isPending ? <Loading what="Checking" /> : null}
        {report === undefined && quick.isError ? <ErrorMessage error={quick.error} /> : null}
        {report && !full.data ? <Sentence report={report} /> : null}
        <div role="status">{full.data ? <Sentence report={full.data} /> : null}</div>
        <button type="button" disabled={full.isPending} onClick={() => full.mutate()}>
          {full.isPending ? "Checking…" : "Run a full check"}
        </button>
        {full.isError ? <ErrorMessage error={full.error} /> : null}
      </section>
      <TechnicalDetails report={report} />
    </section>
  );
}
