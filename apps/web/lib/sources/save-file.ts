/** Hands a Blob to the browser as a file download (the page's only use: the CSV template). */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** The template's file name, by kind of data (the backend names it too; this is the browser's own). */
export const TEMPLATE_FILENAME = {
  BOOKINGS: "modello-prenotazioni.csv",
  LABOR: "modello-personale.csv",
} as const;
