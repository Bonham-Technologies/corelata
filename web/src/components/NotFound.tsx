import type { ReactNode } from "react";
import { Link } from "react-router";
import { useDocumentTitle } from "./frame";

/** A page, report or project that does not exist (CRL-130): a heading that says what was not
 * found, a sentence, and a way on. The browser tab says it too. */
export function NotFound({
  heading = "Page not found",
  children = "There is nothing at this address.",
  to = "/new",
  action = "Start a new report",
}: {
  heading?: string;
  children?: ReactNode;
  to?: string;
  action?: string;
}) {
  useDocumentTitle(`${heading} – Corelata`);
  return (
    <section aria-label="Not found">
      <h1>{heading}</h1>
      <p>{children}</p>
      <p>
        <Link to={to}>{action}</Link>
      </p>
    </section>
  );
}

/** A run the API does not know: its progress and its review say the same. */
export function ReportNotFound() {
  return (
    <NotFound heading="Report not found">This report does not exist, or it was deleted.</NotFound>
  );
}
