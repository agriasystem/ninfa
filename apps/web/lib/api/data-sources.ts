import type {
  DataSourceDomain,
  DataSourcesResponse,
  FileInspectionResponse,
  ImportMapping,
  ImportPreviewResponse,
  ImportResultResponse,
  ImportValidationResponse,
  MappedImportResultResponse,
  MappingCheckResponse,
  SavedImportConfiguration,
} from "@ninfa/contracts";

import { apiBaseUrl, apiRequest, type ApiResult } from "@/lib/api/client";

/**
 * Data-source API V1 (Struttura > Fonti dati). Every call goes through the property's own path: the
 * backend derives the workspace from the property and the session, never from anything sent here.
 * A file travels as the raw request body and is never stored by the API.
 */

export function dataSourcesPath(propertyId: string): string {
  return `/api/v1/properties/${propertyId}/data-sources`;
}

/** GET - the real state of the five cards. */
export function getDataSources(
  propertyId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<DataSourcesResponse>> {
  return apiRequest<DataSourcesResponse>(dataSourcesPath(propertyId), { method: "GET" }, fetchImpl);
}

/** DELETE - switch a source off. The data it already delivered are kept. */
export function removeDataSource(
  propertyId: string,
  dataSourceId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<void>> {
  return apiRequest<void>(
    `${dataSourcesPath(propertyId)}/${dataSourceId}`,
    { method: "DELETE" },
    fetchImpl,
  );
}

/**
 * POST - look at a file before importing it. Writes NOTHING: no source, no job, no row. There is no
 * call that creates a source on its own - the source comes to exist only when `importFile` succeeds.
 */
export function previewImport(
  propertyId: string,
  domain: DataSourceDomain,
  file: Blob,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<ImportPreviewResponse>> {
  const query = new URLSearchParams({ domain });
  return apiRequest<ImportPreviewResponse>(
    `${dataSourcesPath(propertyId)}/import-preview?${query.toString()}`,
    { method: "POST", file },
    fetchImpl,
  );
}

export interface ImportFileArgs {
  propertyId: string;
  /** The kind of data the file carries; the backend creates (or switches back on) its source only if
   * this import succeeds. */
  domain: DataSourceDomain;
  file: File;
  /** The property-local day the file is dated as of (YYYY-MM-DD). Labor only; never the server clock. */
  snapshotLocalDate?: string;
}

/** POST - import the file through the same services the pilot's own tooling uses. */
export function importFile(
  { propertyId, domain, file, snapshotLocalDate }: ImportFileArgs,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<ImportResultResponse>> {
  const query = new URLSearchParams({ domain, filename: file.name });
  if (snapshotLocalDate !== undefined) query.set("snapshot_local_date", snapshotLocalDate);
  return apiRequest<ImportResultResponse>(
    `${dataSourcesPath(propertyId)}/imports?${query.toString()}`,
    { method: "POST", file },
    fetchImpl,
  );
}

/** GET - the column row of the canonical CSV of a domain, as a file the browser can save. `null` when it
 * cannot be fetched (the page then simply does not offer the download). */
export async function downloadTemplate(
  propertyId: string,
  domain: Exclude<DataSourceDomain, "COSTS">,
  fetchImpl: typeof fetch = fetch,
): Promise<Blob | null> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) return null;
  try {
    const response = await fetchImpl(
      `${baseUrl.replace(/\/+$/, "")}${dataSourcesPath(propertyId)}/templates/${domain}`,
      { credentials: "include", cache: "no-store" },
    );
    return response.ok ? await response.blob() : null;
  } catch {
    return null;
  }
}

// --- Smart Import: the hotel's own CSV / Excel file -----------------------------------------------------

/** A file as base64 text (the matched import sends it inside a JSON body: a matching is structured data). */
export function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("The file could not be read"));
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      resolve(text.slice(text.indexOf(",") + 1)); // "data:...;base64,<payload>"
    };
    reader.readAsDataURL(file);
  });
}

/**
 * POST - read a CSV / Excel file and get NINFA's proposal for what each column means. Writes NOTHING: no
 * source, no job, no saved configuration.
 */
export function inspectFile(
  propertyId: string,
  domain: DataSourceDomain,
  file: File,
  sheetName?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<FileInspectionResponse>> {
  const query = new URLSearchParams({ domain, filename: file.name });
  if (sheetName !== undefined) query.set("sheet_name", sheetName);
  return apiRequest<FileInspectionResponse>(
    `${dataSourcesPath(propertyId)}/import-inspection?${query.toString()}`,
    { method: "POST", file },
    fetchImpl,
  );
}

/** POST - is this matching of columns enough to import? The backend's own rules answer; no file is sent. */
export function checkMapping(
  propertyId: string,
  domain: DataSourceDomain,
  mapping: ImportMapping,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<MappingCheckResponse>> {
  return apiRequest<MappingCheckResponse>(
    `${dataSourcesPath(propertyId)}/import-mapping-check`,
    { method: "POST", body: { domain, mapping } },
    fetchImpl,
  );
}

export interface MatchedFileArgs {
  propertyId: string;
  domain: DataSourceDomain;
  file: File;
  /** The person's matching, or `null` to use the configuration saved for this kind of data. */
  mapping: ImportMapping | null;
}

/** POST - judge every row of the file with this matching, exactly as the import will. Writes NOTHING. */
export async function validateImport(
  { propertyId, domain, file, mapping }: MatchedFileArgs,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<ImportValidationResponse>> {
  return apiRequest<ImportValidationResponse>(
    `${dataSourcesPath(propertyId)}/import-validation`,
    {
      method: "POST",
      body: { domain, filename: file.name, file_base64: await fileToBase64(file), mapping },
    },
    fetchImpl,
  );
}

export interface MatchedImportArgs extends MatchedFileArgs {
  /** Remember the matching once the import has succeeded (only meaningful with a `mapping`). */
  saveConfiguration: boolean;
  /** The property-local day the file is dated as of (YYYY-MM-DD). Labor only; never the server clock. */
  snapshotLocalDate?: string;
}

/** POST - import with the person's matching of columns. The source exists only if this succeeds. */
export async function importMatchedFile(
  { propertyId, domain, file, mapping, saveConfiguration, snapshotLocalDate }: MatchedImportArgs,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<MappedImportResultResponse>> {
  return apiRequest<MappedImportResultResponse>(
    `${dataSourcesPath(propertyId)}/imports/mapped`,
    {
      method: "POST",
      body: {
        domain,
        filename: file.name,
        file_base64: await fileToBase64(file),
        mapping,
        save_configuration: saveConfiguration,
        snapshot_local_date: snapshotLocalDate ?? null,
      },
    },
    fetchImpl,
  );
}

/** GET - how this source's files are read, as it was saved. */
export function getImportConfiguration(
  propertyId: string,
  dataSourceId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<SavedImportConfiguration>> {
  return apiRequest<SavedImportConfiguration>(
    `${dataSourcesPath(propertyId)}/${dataSourceId}/import-configuration`,
    { method: "GET" },
    fetchImpl,
  );
}

/** DELETE - forget how this source's files are read. The source and everything imported stay. */
export function forgetImportConfiguration(
  propertyId: string,
  dataSourceId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiResult<void>> {
  return apiRequest<void>(
    `${dataSourcesPath(propertyId)}/${dataSourceId}/import-configuration`,
    { method: "DELETE" },
    fetchImpl,
  );
}
