// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MiaAnswerResponse } from "@ninfa/contracts";

import { useMiaConversation, type UseMiaConversationOptions } from "./use-mia-conversation";

const sendMock = vi.fn();
const listMock = vi.fn();
const getMock = vi.fn();

vi.mock("@/lib/api/mia", () => ({
  sendMiaMessage: (...args: unknown[]) => sendMock(...args),
  listMiaConversations: (...args: unknown[]) => listMock(...args),
  getMiaConversation: (...args: unknown[]) => getMock(...args),
}));

function reply(
  overrides: Partial<MiaAnswerResponse> = {},
): { ok: true; data: MiaAnswerResponse } {
  return {
    ok: true,
    data: {
      status: "ANSWERED",
      answer: "Una risposta.",
      limitations: [],
      grounding_refs: [],
      conversation_id: "conv-1",
      ...overrides,
    },
  };
}

function pending() {
  let resolve: (value: unknown) => void = () => undefined;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

const BASE: UseMiaConversationOptions = { propertyId: "prop-1", asOfLocalDate: "2026-10-08" };

function setup(options: Partial<UseMiaConversationOptions> = {}) {
  return renderHook((props: UseMiaConversationOptions) => useMiaConversation(props), {
    initialProps: { ...BASE, ...options },
  });
}

async function settled() {
  await act(async () => undefined);
}

beforeEach(() => {
  sendMock.mockReset().mockResolvedValue(reply());
  listMock.mockReset().mockResolvedValue({ ok: true, data: { conversations: [] } });
  getMock.mockReset();
});

describe("useMiaConversation - sending", () => {
  it("starts idle with nothing on screen, and a first message starts a conversation", async () => {
    const { result } = setup();
    await settled();
    expect(result.current.exchanges).toEqual([]);
    expect(result.current.status).toBe("idle");
    expect(result.current.conversationId).toBeNull();

    let accepted = false;
    act(() => {
      accepted = result.current.send("  Perché oggi non ho Decision?  ");
    });

    expect(accepted).toBe(true);
    expect(result.current.status).toBe("sending");
    expect(result.current.exchanges).toEqual([
      { id: 0, question: "Perché oggi non ho Decision?", state: { kind: "loading" } },
    ]);
    await waitFor(() => expect(result.current.status).toBe("idle"));
    expect(sendMock).toHaveBeenCalledWith("prop-1", {
      message: "Perché oggi non ho Decision?",
      asOfLocalDate: "2026-10-08",
      conversationId: null,
      uiContext: {},
    });
    expect(result.current.exchanges[0]?.state).toEqual({
      kind: "answered",
      answer: "Una risposta.",
      limitations: [],
    });
    expect(result.current.conversationId).toBe("conv-1");
  });

  it("continues the conversation by its id, and never sends a history", async () => {
    const { result } = setup();
    await settled();
    act(() => void result.current.send("Prima?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    act(() => void result.current.send("E dopo?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    expect(sendMock).toHaveBeenLastCalledWith("prop-1", {
      message: "E dopo?",
      asOfLocalDate: "2026-10-08",
      conversationId: "conv-1",
      uiContext: {},
    });
    expect(result.current.exchanges).toHaveLength(2);
    for (const [, input] of sendMock.mock.calls as [string, Record<string, unknown>][]) {
      expect(input).not.toHaveProperty("history");
      expect(Object.keys(input).sort()).toEqual([
        "asOfLocalDate",
        "conversationId",
        "message",
        "uiContext",
      ]);
    }
  });

  it("reads the screen's hint at the moment of sending, not when the hook was created", async () => {
    let hint: Record<string, unknown> = { route: "/dati", section: "costs" };
    const { result } = setup({ getUiContext: () => hint });
    await settled();

    act(() => void result.current.send("Perché?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));
    hint = { route: "/dati", section: "labor", period_days: 7 };
    act(() => void result.current.send("E qui?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    expect(sendMock).toHaveBeenNthCalledWith(1, "prop-1", expect.objectContaining({
      uiContext: { route: "/dati", section: "costs" },
    }));
    expect(sendMock).toHaveBeenNthCalledWith(2, "prop-1", expect.objectContaining({
      uiContext: { route: "/dati", section: "labor", period_days: 7 },
    }));
  });

  it("sends the business date it has NOW (a new date does not drop the conversation)", async () => {
    const { result, rerender } = setup();
    await settled();
    act(() => void result.current.send("Prima?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    rerender({ ...BASE, asOfLocalDate: "2026-10-09" });
    act(() => void result.current.send("E domani?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({
      asOfLocalDate: "2026-10-09",
      conversationId: "conv-1",
    }));
    expect(result.current.exchanges).toHaveLength(2);
  });

  it("refuses empty or whitespace-only text without calling anything", async () => {
    const { result } = setup();
    await settled();

    let accepted = true;
    act(() => {
      accepted = result.current.send("   \n ");
    });

    expect(accepted).toBe(false);
    expect(sendMock).not.toHaveBeenCalled();
    expect(result.current.exchanges).toEqual([]);
  });

  it("blocks a double submit in the very same tick (one request in flight)", async () => {
    const request = pending();
    sendMock.mockReturnValueOnce(request.promise);
    const { result } = setup();
    await settled();

    let first = false;
    let second = true;
    act(() => {
      first = result.current.send("Prima");
      second = result.current.send("Seconda"); // same tick, before any render
    });

    expect(first).toBe(true);
    expect(second).toBe(false);
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(result.current.exchanges).toHaveLength(1);

    request.resolve(reply());
    await waitFor(() => expect(result.current.status).toBe("idle"));
    let third = false;
    act(() => {
      third = result.current.send("Terza"); // allowed again once the request has ended
    });
    expect(third).toBe(true);
    await waitFor(() => expect(result.current.status).toBe("idle"));
  });

  it("keeps the newest four exchanges on screen", async () => {
    const { result } = setup();
    await settled();

    for (const n of [1, 2, 3, 4, 5]) {
      act(() => void result.current.send(`D${n}?`));
      await waitFor(() => expect(result.current.status).toBe("idle"));
    }

    expect(result.current.exchanges.map((exchange) => exchange.question)).toEqual([
      "D2?",
      "D3?",
      "D4?",
      "D5?",
    ]);
  });
});

describe("useMiaConversation - what each status becomes", () => {
  it("ANSWERED, INSUFFICIENT_CONTEXT and REFUSED keep their own states", async () => {
    const { result } = setup();
    await settled();

    sendMock.mockResolvedValueOnce(reply({ answer: "Sì.", limitations: ["Solo prenotazioni attuali."] }));
    act(() => void result.current.send("A?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));
    sendMock.mockResolvedValueOnce(reply({ status: "INSUFFICIENT_CONTEXT", answer: "Non ho questo dato." }));
    act(() => void result.current.send("B?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));
    sendMock.mockResolvedValueOnce(reply({ status: "REFUSED", answer: null, conversation_id: null }));
    act(() => void result.current.send("C?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    expect(result.current.exchanges.map((exchange) => exchange.state)).toEqual([
      { kind: "answered", answer: "Sì.", limitations: ["Solo prenotazioni attuali."] },
      { kind: "insufficientContext", answer: "Non ho questo dato.", limitations: [] },
      { kind: "refused" },
    ]);
    expect(result.current.status).toBe("idle"); // a refusal is an answer, not a failure
  });

  it("UNAVAILABLE and a network failure are the SAME outcome, and status says so", async () => {
    const { result } = setup();
    await settled();

    sendMock.mockResolvedValueOnce(reply({ status: "UNAVAILABLE", answer: null, conversation_id: null }));
    act(() => void result.current.send("Provider giù?"));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.exchanges[0]?.state).toEqual({ kind: "unavailable" });

    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "offline" });
    act(() => void result.current.send("Rete giù?"));
    await waitFor(() => expect(result.current.exchanges[1]?.state.kind).toBe("unavailable"));
    expect(result.current.status).toBe("error");
    expect(JSON.stringify(result.current.exchanges)).not.toContain("offline");
  });

  it("an unavailable turn leaves no conversation behind", async () => {
    const { result } = setup();
    await settled();

    sendMock.mockResolvedValueOnce({ ok: false, status: 500, code: "UNKNOWN_ERROR", message: "x" });
    act(() => void result.current.send("Persa?"));
    await waitFor(() => expect(result.current.status).toBe("error"));

    expect(result.current.conversationId).toBeNull();
    act(() => void result.current.send("Buona?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({ conversationId: null }));
  });
});

describe("useMiaConversation - retry", () => {
  it("re-sends the SAME message into the same conversation, on the same exchange", async () => {
    const { result } = setup();
    await settled();
    act(() => void result.current.send("Prima?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));
    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    act(() => void result.current.send("Seconda?"));
    await waitFor(() => expect(result.current.status).toBe("error"));
    const failed = result.current.exchanges[1];

    let accepted = false;
    act(() => {
      accepted = result.current.retry(failed?.id ?? -1);
    });
    expect(accepted).toBe(true);
    expect(result.current.exchanges[1]?.state).toEqual({ kind: "loading" });
    await waitFor(() => expect(result.current.status).toBe("idle"));

    expect(result.current.exchanges).toHaveLength(2); // no third exchange: the same one was retried
    expect(result.current.exchanges[1]?.state.kind).toBe("answered");
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({
      message: "Seconda?",
      conversationId: "conv-1",
    }));
  });

  it("retrying an exchange that is gone does nothing", async () => {
    const { result } = setup();
    await settled();

    let accepted = true;
    act(() => {
      accepted = result.current.retry(999);
    });

    expect(accepted).toBe(false);
    expect(sendMock).not.toHaveBeenCalled();
  });
});

describe("useMiaConversation - starting over", () => {
  it("forgets the conversation here: the next message starts a NEW one", async () => {
    const { result } = setup();
    await settled();
    act(() => void result.current.send("Prima?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    let started = false;
    act(() => {
      started = result.current.startNew();
    });

    expect(started).toBe(true);
    expect(result.current.exchanges).toEqual([]);
    expect(result.current.conversationId).toBeNull();
    act(() => void result.current.send("Nuova?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({ conversationId: null }));
  });

  it("is not possible while a request is running", async () => {
    sendMock.mockReturnValueOnce(new Promise(() => undefined));
    const { result } = setup();
    await settled();
    act(() => void result.current.send("Lenta?"));

    let started = true;
    act(() => {
      started = result.current.startNew();
    });

    expect(started).toBe(false);
    expect(result.current.exchanges).toHaveLength(1);
  });
});

describe("useMiaConversation - restoring", () => {
  const STORED = {
    id: "conv-9",
    title: "t",
    updated_at: "2026-10-08T09:00:00Z",
    messages: [
      { role: "user", content: "Perché venerdì è debole?", created_at: "2026-10-08T08:59:00Z", limitations: [] },
      {
        role: "assistant",
        content: "Perché le prenotazioni sono poche.",
        created_at: "2026-10-08T09:00:00Z",
        status: "ANSWERED",
        limitations: [],
      },
    ],
  };

  function storedExists() {
    listMock.mockResolvedValue({
      ok: true,
      data: { conversations: [{ id: "conv-9", title: "t", updated_at: "2026-10-08T09:00:00Z", message_count: 2 }] },
    });
    getMock.mockResolvedValue({ ok: true, data: STORED });
  }

  it("brings back the latest conversation of the property and continues it", async () => {
    storedExists();
    const { result } = setup();

    expect(result.current.restoring).toBe(true);
    await waitFor(() => expect(result.current.restoring).toBe(false));

    expect(listMock).toHaveBeenCalledWith("prop-1");
    expect(getMock).toHaveBeenCalledWith("prop-1", "conv-9");
    expect(result.current.exchanges.map((exchange) => exchange.question)).toEqual(["Perché venerdì è debole?"]);
    expect(result.current.conversationId).toBe("conv-9");
    act(() => void result.current.send("E sabato?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({ conversationId: "conv-9" }));
  });

  it("restores nothing - and says nothing - when there is none or it cannot be read", async () => {
    const empty = setup();
    await waitFor(() => expect(empty.result.current.restoring).toBe(false));
    expect(empty.result.current.exchanges).toEqual([]);

    listMock.mockResolvedValue({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const failed = setup({ propertyId: "prop-2" });
    await waitFor(() => expect(failed.result.current.restoring).toBe(false));
    expect(failed.result.current.exchanges).toEqual([]);
    expect(failed.result.current.status).toBe("idle");
  });

  it("does not restore when told not to (the panel's own choice)", async () => {
    storedExists();
    const { result } = setup({ restore: false });
    await settled();

    expect(listMock).not.toHaveBeenCalled();
    expect(result.current.restoring).toBe(false);
    expect(result.current.exchanges).toEqual([]);
  });

  it("never overwrites what the person already sent with a conversation that arrives late", async () => {
    const late = pending();
    listMock.mockReturnValue(late.promise);
    const { result } = setup();
    act(() => void result.current.send("Subito?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    storedExists();
    late.resolve({
      ok: true,
      data: { conversations: [{ id: "conv-9", title: "t", updated_at: "2026-10-08T09:00:00Z", message_count: 2 }] },
    });
    await settled();

    expect(result.current.exchanges.map((exchange) => exchange.question)).toEqual(["Subito?"]);
    expect(result.current.conversationId).toBe("conv-1");
  });

  it("never brings a conversation back after the person started over", async () => {
    const late = pending();
    listMock.mockReturnValue(late.promise);
    const { result } = setup();

    act(() => void result.current.startNew());
    storedExists();
    late.resolve({
      ok: true,
      data: { conversations: [{ id: "conv-9", title: "t", updated_at: "2026-10-08T09:00:00Z", message_count: 2 }] },
    });
    await settled();

    expect(result.current.exchanges).toEqual([]);
  });

  it("replaces a conversation the server no longer has with a new one - once, silently", async () => {
    storedExists();
    const { result } = setup();
    await waitFor(() => expect(result.current.conversationId).toBe("conv-9"));
    sendMock
      .mockResolvedValueOnce({ ok: false, status: 404, code: "CONVERSATION_NOT_FOUND", message: "x" })
      .mockResolvedValueOnce(reply({ answer: "Nuova risposta.", conversation_id: "conv-new" }));

    act(() => void result.current.send("E sabato?"));
    await waitFor(() => expect(result.current.status).toBe("idle"));

    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock).toHaveBeenNthCalledWith(1, "prop-1", expect.objectContaining({ conversationId: "conv-9" }));
    expect(sendMock).toHaveBeenNthCalledWith(2, "prop-1", expect.objectContaining({ conversationId: null }));
    expect(result.current.conversationId).toBe("conv-new");
    expect(result.current.exchanges.at(-1)?.state.kind).toBe("answered");
  });

  it("does not loop on a 404 that is not about the conversation (it asks twice at most)", async () => {
    storedExists();
    const { result } = setup();
    await waitFor(() => expect(result.current.conversationId).toBe("conv-9"));
    sendMock.mockResolvedValue({ ok: false, status: 404, code: "PROPERTY_NOT_FOUND", message: "x" });

    act(() => void result.current.send("Ancora?"));
    await waitFor(() => expect(result.current.status).toBe("error"));

    expect(sendMock).toHaveBeenCalledTimes(2);
  });
});

describe("useMiaConversation - a different property, or no component at all", () => {
  it("a property change resets the conversation, and a late answer of the old one is dropped", async () => {
    const stale = pending();
    sendMock.mockReturnValueOnce(stale.promise);
    const { result, rerender } = setup();
    await settled();
    act(() => void result.current.send("Lenta?"));

    rerender({ ...BASE, propertyId: "prop-2" });
    stale.resolve(reply({ answer: "Risposta tardiva della proprietà vecchia." }));
    await settled();

    expect(result.current.exchanges).toEqual([]);
    expect(result.current.conversationId).toBeNull();
    expect(result.current.status).toBe("idle");
    // ...and the stale request does not block the new property
    let accepted = false;
    act(() => {
      accepted = result.current.send("Ora?");
    });
    expect(accepted).toBe(true);
    await waitFor(() => expect(result.current.status).toBe("idle"));
    expect(sendMock).toHaveBeenLastCalledWith("prop-2", expect.objectContaining({
      message: "Ora?",
      conversationId: null,
    }));
  });

  it("restores the conversation of the NEW property after a change", async () => {
    const { result, rerender } = setup();
    await settled();
    listMock.mockClear();

    rerender({ ...BASE, propertyId: "prop-2" });
    await settled();

    expect(listMock).toHaveBeenCalledWith("prop-2");
    expect(result.current.exchanges).toEqual([]);
  });

  it("an answer that lands after the component is gone is dropped without an error", async () => {
    const request = pending();
    sendMock.mockReturnValueOnce(request.promise);
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { result, unmount } = setup();
    await settled();
    act(() => void result.current.send("Lenta?"));

    unmount();
    request.resolve(reply());
    await settled();

    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});
