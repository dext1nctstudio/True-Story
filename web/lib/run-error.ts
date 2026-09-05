/** Turn backend diagnostics into bounded, actionable copy for the workspace. */
export function presentRunError(error: string | null | undefined): string | null {
  if (!error) return null;

  if (error.includes("File name too long")) {
    return (
      "This run failed during ingest because pasted script text was mistaken for a " +
      "filename. That ingest issue is fixed; submit the same draft again."
    );
  }

  const limit = 240;
  return error.length > limit ? `${error.slice(0, limit - 1)}…` : error;
}
