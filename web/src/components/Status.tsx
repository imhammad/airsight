import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import styles from "./Status.module.css";

export function Loading({ label }: { label: string }) {
  return (
    <p className={styles.status} role="status">
      {label}
    </p>
  );
}

/** A failed request, in words a visitor understands, with a way to try again. */
export function ErrorMessage({
  error,
  onRetry,
}: {
  error: Error;
  onRetry: () => void;
}) {
  const detail =
    error instanceof ApiError && error.status === 429
      ? "Too many requests in a minute. Wait a moment, then try again."
      : error instanceof ApiError
        ? error.message
        : "We couldn't reach AirSight. Check your connection.";
  return (
    <div className={styles.error} role="alert">
      <p>{detail}</p>
      <button type="button" className={styles.retry} onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className={styles.status}>{children}</p>;
}
