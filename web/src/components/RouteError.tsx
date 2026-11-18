import { Link, useRouteError } from "react-router";
import { ErrorMessage } from "./ErrorMessage";

export function RouteError() {
  const error = useRouteError();
  return (
    <section aria-label="Error">
      <h1>Something went wrong</h1>
      <ErrorMessage error={error} />
      <p>
        <Link to="/new">Back to the start</Link>
      </p>
    </section>
  );
}
