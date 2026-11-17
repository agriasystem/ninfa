import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getMiaConversation,
  listMiaConversations,
  miaConversationPath,
  miaConversationsPath,
  miaMessagesPath,
  sendMiaMessage,
} from "./mia";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ANSWER = {
  status: "ANSWERED",
  answer: "Una risposta.",
  limitations: [],
  grounding_refs: [],
  conversation_id: "11111111-1111-4111-8111-111111111111",
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Mia paths", () => {
  it("are all scoped by the property in the PATH", () => {
    expect(miaMessagesPath("prop-1")).toBe("/api/v1/properties/prop-1/mia/messages");
    expect(miaConversationsPath("prop-1")).toBe("/api/v1/properties/prop-1/mia/conversations");
    expect(miaConversationPath("prop-1", "conv-1")).toBe(
      "/api/v1/properties/prop-1/mia/conversations/conv-1",
    );
  });

  it("encodes a conversation id, so it can never add a path segment", () => {
    expect(miaConversationPath("prop-1", "../x/y")).toBe(
      "/api/v1/properties/prop-1/mia/conversations/..%2Fx%2Fy",
    );
  });
});

describe("sendMiaMessage", () => {
  it("POSTs the message and the explicit business date, with credentials and no-store", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(ANSWER));

    const result = await sendMiaMessage(
      "prop-1",
      { message: "Perché oggi non ho Decision?", asOfLocalDate: "2026-10-08" },
      fetchImpl,
    );

    expect(result).toEqual({ ok: true, data: ANSWER });
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example/api/v1/properties/prop-1/mia/messages");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(JSON.parse(init.body as string)).toEqual({
      message: "Perché oggi non ho Decision?",
      as_of_local_date: "2026-10-08",
    });
  });

  it("a first message carries no conversation id and no screen hint (left out, not null)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(ANSWER));

    await sendMiaMessage(
      "prop-1",
      { message: "Ciao", asOfLocalDate: "2026-10-08", conversationId: null, uiContext: {} },
      fetchImpl,
    );

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(Object.keys(JSON.parse(init.body as string)).sort()).toEqual([
      "as_of_local_date",
      "message",
    ]);
  });

  it("continues a conversation by its id and carries the screen hint when there is one", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(ANSWER));

    await sendMiaMessage(
      "prop-1",
      {
        message: "E sabato?",
        asOfLocalDate: "2026-10-08",
        conversationId: "conv-1",
        uiContext: { route: "/dati", section: "costs", period_days: 7 },
      },
      fetchImpl,
    );

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      message: "E sabato?",
      as_of_local_date: "2026-10-08",
      conversation_id: "conv-1",
      ui_context: { route: "/dati", section: "costs", period_days: 7 },
    });
  });

  it("never sends a history, a tool, a property or a workspace in the body", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(ANSWER));

    await sendMiaMessage(
      "prop-1",
      {
        message: "Ciao",
        asOfLocalDate: "2026-10-08",
        conversationId: "conv-1",
        uiContext: { route: "/oggi" },
      },
      fetchImpl,
    );

    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    for (const forbidden of ["history", "messages", "tools", "property_id", "workspace_id", "question"]) {
      expect(body).not.toHaveProperty(forbidden);
    }
  });

  it("a network failure is a failed result, never a throw", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi.fn().mockRejectedValue(new Error("offline"));

    const result = await sendMiaMessage(
      "prop-1",
      { message: "Ciao", asOfLocalDate: "2026-10-08" },
      fetchImpl,
    );

    expect(result).toMatchObject({ ok: false, status: 0, code: "NETWORK_ERROR" });
  });

  it("a backend error envelope comes back typed (the screen never shows its text)", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ error: { code: "PROPERTY_NOT_FOUND", message: "Property not found" } }, 404),
      );

    const result = await sendMiaMessage(
      "prop-1",
      { message: "Ciao", asOfLocalDate: "2026-10-08" },
      fetchImpl,
    );

    expect(result).toEqual({
      ok: false,
      status: 404,
      code: "PROPERTY_NOT_FOUND",
      message: "Property not found",
    });
  });
});

describe("listMiaConversations / getMiaConversation", () => {
  it("GET the recent conversations of the person about the property", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const body = {
      conversations: [{ id: "c1", title: "t", updated_at: "2026-10-08T09:00:00Z", message_count: 2 }],
    };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body));

    const result = await listMiaConversations("prop-1", fetchImpl);

    expect(result).toEqual({ ok: true, data: body });
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example/api/v1/properties/prop-1/mia/conversations");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    expect(init.cache).toBe("no-store");
    expect(init.body).toBeUndefined();
  });

  it("GET one conversation by its id", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const body = { id: "c1", title: "t", updated_at: "2026-10-08T09:00:00Z", messages: [] };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(body));

    const result = await getMiaConversation("prop-1", "c1", fetchImpl);

    expect(result).toEqual({ ok: true, data: body });
    expect((fetchImpl.mock.calls[0] as [string])[0]).toBe(
      "https://api.example/api/v1/properties/prop-1/mia/conversations/c1",
    );
  });

  it("a conversation of someone else (or a missing one) is the same 404", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example");
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ error: { code: "CONVERSATION_NOT_FOUND", message: "x" } }, 404));

    const result = await getMiaConversation("prop-1", "c9", fetchImpl);

    expect(result).toMatchObject({ ok: false, status: 404 });
  });
});
