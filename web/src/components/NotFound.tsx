import { Link } from "react-router";

export function NotFound() {
  return (
    <section aria-label="Not found">
      <h1>Page not found</h1>
      <p>
        <Link to="/new">Start a new report</Link>
      </p>
    </section>
  );
}
