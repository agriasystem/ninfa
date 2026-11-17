// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MiaAnswerResponse } from "@ninfa/contracts";

import {
  PAGE_ROUTES,
  PageContextProvider,
  usePublishPage,
  type PageState,
} from "@/lib/page-context/page-context";

import { MiaLauncher } from "./mia-panel";

const sendMock = vi.fn();
const listMock = vi.fn();
const getMock = vi.fn();

vi.mock("@/lib/api/mia", () => ({
  sendMiaMessage: (...args: unknown[]) => sendMock(...args),
  listMiaConversations: (...args: unknown[]) => listMock(...args),
  getMiaConversation: (...args: unknown[]) => getMock(...args),
}));

function answered(
  answer: string,
  conversationId: string | null = "conv-1",
): { ok: true; data: MiaAnswerResponse } {
  return {
    ok: true,
    data: { status: "ANSWERED", answer, limitations: [], grounding_refs: [], conversation_id: conversationId },
  };
}

function Publisher({ state }: { state: PageState }) {
  usePublishPage(state);
  return null;
}

function renderLauncher(state: PageState = {}, propertyId = "prop-1") {
  return render(
    <PageContextProvider>
      <Publisher state={state} />
      <MiaLauncher propertyId={propertyId} timeZone="Europe/Rome" />
    </PageContextProvider>,
  );
}

function launcher() {
  return screen.getByRole("button", { name: "Apri la conversazione con Mia" });
}

function dialog() {
  return screen.getByRole("dialog", { name: "Conversazione con Mia" });
}

function input() {
  return screen.getByRole("textbox", { name: "La tua domanda per Mia" }) as HTMLTextAreaElement;
}

async function open(user: ReturnType<typeof userEvent.setup>) {
  await user.click(launcher());
  return dialog();
}

beforeEach(() => {
  // 8 October 2026, 22:30 UTC = 00:30 on the 9th in Rome: the property's "today" is NOT the UTC date.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-08T22:30:00Z"));
  sendMock.mockReset().mockResolvedValue(answered("Una risposta fondata."));
  listMock.mockReset().mockResolvedValue({ ok: true, data: { conversations: [] } });
  getMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("MiaLauncher - the entry", () => {
  it("is one quiet, labelled button; nothing else is on screen until it is pressed", () => {
    renderLauncher();

    const button = launcher();
    expect(button.textContent).toBe("Parla con Mia");
    expect(button.getAttribute("aria-haspopup")).toBe("dialog");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(listMock).not.toHaveBeenCalled(); // a page that never opens Mia never calls her
  });

  it("is not called 'Chiedi a Mia': the Decision Detail already has a control with that name", () => {
    renderLauncher();

    expect(screen.queryByRole("button", { name: "Chiedi a Mia" })).toBeNull();
  });

  it("opens a non-modal dialog, with focus in the composer", async () => {
    const user = userEvent.setup();
    renderLauncher();

    await open(user);

    expect(dialog().getAttribute("aria-modal")).toBe("false");
    expect(launcher().getAttribute("aria-expanded")).toBe("true");
    expect(launcher().getAttribute("aria-controls")).toBe(dialog().id);
    expect(document.activeElement).toBe(input());
    expect(
      within(dialog()).getByText("Chiedi a Mia di questa pagina, dei dati della struttura o di come funziona NINFA."),
    ).not.toBeNull();
  });

  it("the launcher toggles the panel", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.click(launcher());

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(launcher().getAttribute("aria-expanded")).toBe("false");
  });
});

describe("MiaLauncher - closing, and where the focus goes", () => {
  it("Escape closes the panel and hands the focus back to the launcher", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(launcher());
  });

  it("the close button does the same", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.click(screen.getByRole("button", { name: "Chiudi la conversazione con Mia" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(launcher());
  });

  it("Escape pressed while composing text with an IME belongs to the composition", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    fireEvent.keyDown(input(), { key: "Escape", isComposing: true });

    expect(screen.queryByRole("dialog")).not.toBeNull();
  });

  it("Escape does nothing when the panel is closed", async () => {
    const user = userEvent.setup();
    renderLauncher();

    await user.keyboard("{Escape}");

    expect(document.activeElement).not.toBe(launcher());
  });
});

describe("MiaPanel - sending", () => {
  it("sends the text with the property's OWN business date, never the browser's or UTC's", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.type(input(), "Perché il costo per camera non è disponibile?{Enter}");

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith("prop-1", {
      message: "Perché il costo per camera non è disponibile?",
      asOfLocalDate: "2026-10-09", // 00:30 in Rome, already the 9th
      conversationId: null,
      uiContext: {},
    });
    expect(input().value).toBe("");
    expect(await screen.findByText("Una risposta fondata.")).not.toBeNull();
  });

  it("is page-aware ONLY through the request body: the hint the screen published travels with it", async () => {
    const user = userEvent.setup();
    renderLauncher({ route: PAGE_ROUTES.dati, section: "labor", periodDays: 7 });
    await open(user);

    await user.type(input(), "Perché è così alto?{Enter}");

    expect(sendMock).toHaveBeenCalledWith("prop-1", {
      message: "Perché è così alto?",
      asOfLocalDate: "2026-10-09",
      conversationId: null,
      uiContext: { route: "/dati", section: "labor", period_days: 7 },
    });
    // The body carries the text and the hint - never a history, a tool or the page's own text.
    const [, input0] = sendMock.mock.calls[0] as [string, Record<string, unknown>];
    expect(Object.keys(input0).sort()).toEqual(["asOfLocalDate", "conversationId", "message", "uiContext"]);
  });

  it("the second message continues the conversation by its id", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);
    await user.type(input(), "Prima?{Enter}");
    await screen.findByText("Una risposta fondata.");

    sendMock.mockResolvedValueOnce(answered("Seconda risposta."));
    await user.type(input(), "E poi?{Enter}");
    await screen.findByText("Seconda risposta.");

    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({
      message: "E poi?",
      conversationId: "conv-1",
    }));
  });

  it("Shift+Enter is a new line, an empty text sends nothing, and one request runs at a time", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.keyboard("{Enter}");
    expect(sendMock).not.toHaveBeenCalled();
    await user.type(input(), "Prima riga{Shift>}{Enter}{/Shift}Seconda riga");
    expect(input().value).toBe("Prima riga\nSeconda riga");
    expect(sendMock).not.toHaveBeenCalled();

    sendMock.mockReturnValueOnce(new Promise(() => undefined));
    await user.keyboard("{Enter}");
    await user.type(input(), "Un'altra{Enter}");

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith("prop-1", expect.objectContaining({
      message: "Prima riga\nSeconda riga",
    }));
    expect(input().value).toBe("Un'altra"); // the draft is untouched while Mia answers
  });

  it("says 'Mia sta analizzando…' while the request runs - non-technical, and the field stays usable", async () => {
    const request: { resolve: (value: unknown) => void } = { resolve: () => undefined };
    sendMock.mockReturnValueOnce(new Promise((resolve) => (request.resolve = resolve)));
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.type(input(), "Ciao{Enter}");

    expect(within(dialog()).getByRole("status").textContent).toContain("Mia sta analizzando…");
    expect(
      (within(dialog()).getByRole("button", { name: "Mia sta analizzando…" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(input().disabled).toBe(false);
    expect(document.activeElement).toBe(input());

    await act(async () => request.resolve(answered("Fatto.")));
    expect(await screen.findByText("Fatto.")).not.toBeNull();
  });

  it("shows the dignified error for a failure, and a manual retry re-sends the SAME message", async () => {
    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "offline" });
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.type(input(), "Ciao{Enter}");

    expect(await screen.findByText("Al momento non riesco a completare l'analisi con Mia.")).not.toBeNull();
    expect(screen.getByText("I dati NINFA restano disponibili normalmente.")).not.toBeNull();
    expect(screen.queryByText("offline")).toBeNull();
    sendMock.mockResolvedValueOnce(answered("Ora funziona."));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(await screen.findByText("Ora funziona.")).not.toBeNull();
    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({ message: "Ciao" }));
  });

  it("a refusal is shown as such, in Mia's name", async () => {
    sendMock.mockResolvedValueOnce({
      ok: true,
      data: { status: "REFUSED", answer: null, limitations: [], grounding_refs: [], conversation_id: null },
    });
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    await user.type(input(), "Abbassa il prezzo di venerdì{Enter}");

    expect(await screen.findByText("Mia non può rispondere a questa domanda.")).not.toBeNull();
  });

  it("never names a tool, a source or a model anywhere on the panel", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);
    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(dialog().textContent).not.toMatch(/openai|gpt|chatgpt|claude|modello|strument|tool/iu);
  });
});

describe("MiaPanel - the conversation", () => {
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

  it("brings back the latest conversation when the panel is opened, and continues it", async () => {
    storedExists();
    const user = userEvent.setup();
    renderLauncher();
    await open(user);

    expect(await screen.findByText("Perché le prenotazioni sono poche.")).not.toBeNull();
    expect(within(dialog()).queryByText(/Chiedi a Mia di questa pagina/u)).toBeNull(); // not an empty panel
    sendMock.mockResolvedValueOnce(answered("E sabato.", "conv-9"));
    await user.type(input(), "E sabato?{Enter}");
    await screen.findByText("E sabato.");
    expect(sendMock).toHaveBeenCalledWith("prop-1", expect.objectContaining({ conversationId: "conv-9" }));
  });

  it("closing and reopening brings the same conversation back from the server", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);
    await user.type(input(), "Prima?{Enter}");
    await screen.findByText("Una risposta fondata.");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    storedExists();

    await open(user);

    expect(await screen.findByText("Perché le prenotazioni sono poche.")).not.toBeNull();
    expect(listMock).toHaveBeenCalledTimes(2);
  });

  it("'Nuova conversazione' starts over, and is only offered once there is something to leave", async () => {
    const user = userEvent.setup();
    renderLauncher();
    await open(user);
    expect(screen.queryByRole("button", { name: "Nuova conversazione" })).toBeNull();
    await user.type(input(), "Prima?{Enter}");
    await screen.findByText("Una risposta fondata.");

    await user.click(screen.getByRole("button", { name: "Nuova conversazione" }));

    expect(screen.queryByText("Una risposta fondata.")).toBeNull();
    expect(document.activeElement).toBe(input());
    sendMock.mockResolvedValueOnce(answered("Nuova.", "conv-2"));
    await user.type(input(), "Altra?{Enter}");
    await screen.findByText("Nuova.");
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", expect.objectContaining({ conversationId: null }));
  });

  it("a different property is a different panel: nothing carries over", async () => {
    const user = userEvent.setup();
    const { rerender } = renderLauncher({}, "prop-1");
    await open(user);
    await user.type(input(), "Prima?{Enter}");
    await screen.findByText("Una risposta fondata.");

    rerender(
      <PageContextProvider>
        <MiaLauncher propertyId="prop-2" timeZone="Europe/Rome" />
      </PageContextProvider>,
    );

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("Una risposta fondata.")).toBeNull();
    await open(user);
    expect(listMock).toHaveBeenLastCalledWith("prop-2");
    await waitFor(() => expect(screen.queryByText("Una risposta fondata.")).toBeNull());
  });
});
