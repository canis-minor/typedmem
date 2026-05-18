/**
 * Errors thrown by TypedMemoryClient. The server returns a structured
 * ``{error, code, details}`` body — these are surfaced verbatim on the
 * thrown error so callers can branch on ``err.code``.
 */
export class TypedMemoryError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    opts: { status: number; code: string; details?: Record<string, unknown> }
  ) {
    super(message);
    this.name = "TypedMemoryError";
    this.status = opts.status;
    this.code = opts.code;
    this.details = opts.details ?? {};
  }
}

/** 401 — invalid or missing auth token. */
export class UnauthenticatedError extends TypedMemoryError {
  constructor(message: string, details?: Record<string, unknown>) {
    super(message, { status: 401, code: "unauthenticated", details });
    this.name = "UnauthenticatedError";
  }
}

/** 404 — memory id / resource not found. */
export class NotFoundError extends TypedMemoryError {
  constructor(message: string, details?: Record<string, unknown>) {
    super(message, { status: 404, code: "not_found", details });
    this.name = "NotFoundError";
  }
}

/** 422 — profile rejected the memory shape (wrong type, missing required field). */
export class ProfileValidationError extends TypedMemoryError {
  constructor(message: string, details?: Record<string, unknown>) {
    super(message, { status: 422, code: "profile_validation_error", details });
    this.name = "ProfileValidationError";
  }
}

/** Build the right error subclass given an HTTP response body. */
export function errorFromResponse(
  status: number,
  body: unknown
): TypedMemoryError {
  // Server bodies have shape {error, code, details} OR {detail: {error, code, details}}
  // (FastAPI's HTTPException wraps in `detail`).
  const payload = unwrap(body);
  const message = payload.error ?? `HTTP ${status}`;
  const code = payload.code ?? `http_${status}`;
  const details = payload.details ?? {};
  switch (code) {
    case "unauthenticated":
      return new UnauthenticatedError(message, details);
    case "not_found":
      return new NotFoundError(message, details);
    case "profile_validation_error":
      return new ProfileValidationError(message, details);
    default:
      return new TypedMemoryError(message, { status, code, details });
  }
}

function unwrap(body: unknown): {
  error?: string;
  code?: string;
  details?: Record<string, unknown>;
} {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (b.detail && typeof b.detail === "object") {
      return b.detail as ReturnType<typeof unwrap>;
    }
    return b as ReturnType<typeof unwrap>;
  }
  return {};
}
