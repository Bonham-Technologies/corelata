import { ApiError } from "../api/client";

export function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong.";
}

export function ErrorMessage({ error }: { error: unknown }) {
  return (
    <p role="alert" className="error">
      {messageOf(error)}
    </p>
  );
}
