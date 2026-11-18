import type { DoctorCheck, DoctorReport } from "../api/types";
import { plural } from "../lib/words";

/** A check whose failure means no report can be written: the model servers (R-M18-8). */
function modelServer(name: string): boolean {
  return name === "backends" || name.startsWith("backend ") || name.startsWith("model ");
}

function failedSentence(check: DoctorCheck): string {
  if (check.name === "database") {
    return "Corelata can't reach its database. Reports can't start until an administrator fixes it.";
  }
  if (modelServer(check.name)) {
    return "The model server isn't answering. Reports can't be written until an administrator fixes it.";
  }
  if (check.name === "storage") {
    return "Corelata can't store files. Uploads and reports fail until an administrator fixes it.";
  }
  if (check.name === "config") {
    return "The configuration has a problem. An administrator needs to fix it; the details are under Technical details.";
  }
  return "Something needs an administrator's attention. The details are under Technical details.";
}

export function reportFailed(report: DoctorReport): boolean {
  return report.checks.some((c) => c.status === "fail");
}

/** Adapted from Coglossa's statusSentence (M18 spec §5.6): what the installation checks mean for
 * the reader, in one sentence; the first failing check decides it. */
export function statusSentence(report: DoctorReport): string {
  const failed = report.checks.find((c) => c.status === "fail");
  if (failed) return failedSentence(failed);
  const notes = report.checks.filter((c) => c.status === "warn").length;
  if (notes === 0) return "Everything is working.";
  return `Everything is working. ${plural(notes, "note")} ${notes === 1 ? "is" : "are"} under Technical details.`;
}
