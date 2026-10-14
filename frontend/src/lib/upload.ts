/** Matches MAX_UPLOAD_BYTES in backend/app/h9n/ingestion/pdf_reader.py. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

/**
 * Checks a chosen file before it is uploaded, so obvious mistakes are caught
 * without a round trip. The API still validates everything itself.
 * Returns a message to show, or null when the file looks fine.
 */
export function validatePdf(file: Pick<File, "name" | "size" | "type">): string | null {
  const looksLikePdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!looksLikePdf) return "Only PDF deal packages are supported right now.";
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `PDFs may be at most ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB; this one is ${formatBytes(file.size)}.`;
  }
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
