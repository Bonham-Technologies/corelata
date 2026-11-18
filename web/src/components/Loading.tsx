export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <p role="status" className="muted">
      {what}…
    </p>
  );
}
