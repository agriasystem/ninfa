import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as dataSourcesApi from "./data-sources";
import {
  dataSourcesPath,
  downloadTemplate,
  getDataSources,
  importFile,
  previewImport,
  removeDataSource,
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
      "dataSourcesPath",
      "downloadTemplate",
      "getDataSources",
      "importFile",
      "previewImport",
      "removeDataSource",
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
