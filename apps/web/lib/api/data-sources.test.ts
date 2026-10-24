// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as dataSourcesApi from "./data-sources";
import {
  checkMapping,
  dataSourcesPath,
  downloadTemplate,
  fileToBase64,
  forgetImportConfiguration,
  getDataSources,
  getImportConfiguration,
  importFile,
  importMatchedFile,
  inspectFile,
  previewImport,
  removeDataSource,
  validateImport,
} from "./data-sources";

const fetchMock = vi.fn();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

function lastCall(): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url, init };
}

describe("the data-source API client", () => {
  it("builds every path under the property, never from anything else", () => {
    expect(dataSourcesPath("p1")).toBe("/api/v1/properties/p1/data-sources");
  });

  it("GETs the cards with the session cookie and no cache", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ property_id: "p1", cards: [], capabilities: [], automatic_integrations: [] }));

    const result = await getDataSources("p1", fetchMock);

    expect(result.ok).toBe(true);
    const { url, init } = lastCall();
    expect(url).toBe("http://api.test/api/v1/properties/p1/data-sources");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
  });

  it("offers NO call that creates a source: it only comes to exist when an import succeeds", () => {
    expect(Object.keys(dataSourcesApi).sort()).toEqual([
      "checkMapping",
      "dataSourcesPath",
      "downloadTemplate",
      "fileToBase64",
      "forgetImportConfiguration",
      "getDataSources",
      "getImportConfiguration",
      "importFile",
      "importMatchedFile",
      "inspectFile",
      "previewImport",
      "removeDataSource",
      "understandFile",
      "validateImport",
    ]);
  });

  it("DELETEs a source and treats 204 as success", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    const result = await removeDataSource("p1", "s1", fetchMock);

    expect(result.ok).toBe(true);
    expect(lastCall().url).toBe("http://api.test/api/v1/properties/p1/data-sources/s1");
    expect(lastCall().init.method).toBe("DELETE");
  });

  it("sends a file for preview as the RAW body, not JSON and not multipart", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ can_import: true }));
    const file = new File(["a,b\n1,2\n"], "x.csv", { type: "text/csv" });

    await previewImport("p1", "LABOR", file, fetchMock);

    const { url, init } = lastCall();
    expect(url).toBe("http://api.test/api/v1/properties/p1/data-sources/import-preview?domain=LABOR");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(file);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/octet-stream");
  });

  it("imports a file with its name in the query and, for labor only, the property-local day", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ succeeded: true }));
    const file = new File(["x"], "personale ottobre.csv");

    await importFile(
      { propertyId: "p1", domain: "LABOR", file, snapshotLocalDate: "2026-10-23" },
      fetchMock,
    );
    let { url } = lastCall();
    expect(url).toBe(
      "http://api.test/api/v1/properties/p1/data-sources/imports?domain=LABOR&filename=personale+ottobre.csv&snapshot_local_date=2026-10-23",
    );

    await importFile({ propertyId: "p1", domain: "BOOKINGS", file }, fetchMock);
    ({ url } = lastCall());
    expect(url).toContain("domain=BOOKINGS");
    expect(url).not.toContain("snapshot_local_date");
    expect(lastCall().init.body).toBe(file);
  });

  it("returns the typed error of the backend and never a raw response", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: { code: "DATA_SOURCE_NOT_FOUND", message: "x" } }, 404));

    const result = await removeDataSource("p1", "s1", fetchMock);

    expect(result).toEqual({ ok: false, status: 404, code: "DATA_SOURCE_NOT_FOUND", message: "x" });
  });

  it("downloads the template as a blob, or nothing when it cannot", async () => {
    fetchMock.mockResolvedValueOnce(new Response("work_date\r\n", { status: 200 }));
    const blob = await downloadTemplate("p1", "LABOR", fetchMock);
    expect(blob).toBeInstanceOf(Blob);
    expect(lastCall().url).toBe("http://api.test/api/v1/properties/p1/data-sources/templates/LABOR");
    expect(lastCall().init.credentials).toBe("include");

    fetchMock.mockResolvedValueOnce(new Response("", { status: 404 }));
    expect(await downloadTemplate("p1", "BOOKINGS", fetchMock)).toBeNull();

    fetchMock.mockRejectedValueOnce(new Error("offline"));
    expect(await downloadTemplate("p1", "BOOKINGS", fetchMock)).toBeNull();
  });
});

// --- Smart Import: the hotel's own CSV / Excel file -------------------------------------------------------------

const MAPPING = {
  columns: [{ header: "Giorno", field: "work_date" as const }],
  constants: {},
  date_order: "DMY" as const,
};

describe("the data-source API client - Smart Import", () => {
  const file = new File(["Giorno;Ore\n26/10/2026;8\n"], "turni-settimana-43.csv", { type: "text/csv" });

  it("turns a file into base64 text, byte for byte", async () => {
    expect(await fileToBase64(new Blob(["ciao è"]))).toBe(btoa(String.fromCharCode(...new TextEncoder().encode("ciao è"))));
    expect(await fileToBase64(new Blob([]))).toBe("");
  });

  it("reads a file as the RAW body, with its own name and the sheet, and writes nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ columns: [] }));

    await inspectFile("p1", "LABOR", file, "Turni", fetchMock);

    const { url, init } = lastCall();
    expect(url).toBe(
      "http://api.test/api/v1/properties/p1/data-sources/import-inspection?domain=LABOR&filename=turni-settimana-43.csv&sheet_name=Turni",
    );
    expect(init.method).toBe("POST");
    expect(init.body).toBe(file);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/octet-stream");
    expect(init.credentials).toBe("include");
  });

  it("checks a matching with a small JSON body and no file", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ valid: false, missing: [["planned_hours", "actual_hours"]], problems: [] }));

    const result = await checkMapping("p1", "LABOR", MAPPING, fetchMock);

    expect(result.ok).toBe(true);
    const { url, init } = lastCall();
    expect(url).toBe("http://api.test/api/v1/properties/p1/data-sources/import-mapping-check");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ domain: "LABOR", mapping: MAPPING });
  });

  it("tries a file with the matching: the file travels as base64 inside JSON, `null` means the saved one", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "READY" }));

    await validateImport({ propertyId: "p1", domain: "LABOR", file, mapping: MAPPING }, fetchMock);
    await validateImport({ propertyId: "p1", domain: "LABOR", file, mapping: null }, fetchMock);

    const [first, second] = fetchMock.mock.calls.map(([, init]) => JSON.parse((init as RequestInit).body as string));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://api.test/api/v1/properties/p1/data-sources/import-validation");
    expect(first).toEqual({
      domain: "LABOR",
      filename: "turni-settimana-43.csv",
      file_base64: await fileToBase64(file),
      mapping: MAPPING,
    });
    expect(second.mapping).toBeNull();
  });

  it("imports with the matching, asking (or not) to remember it, and dates only a labor file", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ succeeded: true }));

    await importMatchedFile(
      { propertyId: "p1", domain: "LABOR", file, mapping: MAPPING, saveConfiguration: true, snapshotLocalDate: "2026-10-23" },
      fetchMock,
    );
    await importMatchedFile(
      { propertyId: "p1", domain: "BOOKINGS", file, mapping: null, saveConfiguration: false },
      fetchMock,
    );

    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://api.test/api/v1/properties/p1/data-sources/imports/mapped");
    const [labor, bookings] = fetchMock.mock.calls.map(([, init]) => JSON.parse((init as RequestInit).body as string));
    expect(labor).toMatchObject({
      domain: "LABOR",
      mapping: MAPPING,
      save_configuration: true,
      snapshot_local_date: "2026-10-23",
    });
    expect(bookings).toMatchObject({ domain: "BOOKINGS", mapping: null, save_configuration: false, snapshot_local_date: null });
    expect(JSON.stringify(labor)).not.toMatch(/data_source_id|dataSourceId/u); // the page names no source
  });

  it("reads and forgets the saved configuration of a source the card already showed", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ columns: [] }));
    await getImportConfiguration("p1", "s1", fetchMock);
    expect(lastCall().url).toBe("http://api.test/api/v1/properties/p1/data-sources/s1/import-configuration");
    expect(lastCall().init.method).toBe("GET");

    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const result = await forgetImportConfiguration("p1", "s1", fetchMock);

    expect(result.ok).toBe(true);
    expect(lastCall().init.method).toBe("DELETE");
  });

  it("hands a failure back as a plain result, never a technical message", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: "IMPORT_IN_PROGRESS", message: "Another import is running", details: null } }, 409),
    );

    const result = await importMatchedFile(
      { propertyId: "p1", domain: "BOOKINGS", file, mapping: MAPPING, saveConfiguration: true },
      fetchMock,
    );

    expect(result).toMatchObject({ ok: false, status: 409, code: "IMPORT_IN_PROGRESS" });
  });
});
