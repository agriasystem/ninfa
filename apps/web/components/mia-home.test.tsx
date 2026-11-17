// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MiaAnswerResponse } from "@ninfa/contracts";

import {
  PAGE_ROUTES,
  PageContextProvider,
  usePublishPage,
  type PageState,
} from "@/lib/page-context/page-context";

import { MiaHome } from "./mia-home";

const sendMock = vi.fn();
const listMock = vi.fn();
const getMock = vi.fn();

vi.mock("@/lib/api/mia", () => ({
  sendMiaMessage: (...args: unknown[]) => sendMock(...args),
  listMiaConversations: (...args: unknown[]) => listMock(...args),
  getMiaConversation: (...args: unknown[]) => getMock(...args),
}));

const QUESTIONS = [
  "Ci sono altri problemi oltre a questo?",
  "Qual è la priorità più urgente oggi?",
  "Quale decisione ha l'impatto economico più alto?",
  "Quali dati ha usato NINFA oggi?",
];

function answered(
  answer: string,
  limitations: string[] = [],
  conversationId: string | null = "conv-1",
): { ok: true; data: MiaAnswerResponse } {
  return {
    ok: true,
    data: {
      status: "ANSWERED",
      answer,
      grounding_refs: [],
      limitations,
      conversation_id: conversationId,
    },
  };
}

/** What a message to Mia carries: the text, the business date, the conversation id (none for the
 * first message) and the hint about the screen - NEVER a history. */
function sentOf(message: string, conversationId: string | null = null) {
  return { message, asOfLocalDate: "2026-10-08", conversationId, uiContext: {} };
}

function pending() {
  let resolve: (value: unknown) => void = () => undefined;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

function renderMia(onFirstInput = vi.fn()) {
  const utils = render(<MiaHome propertyId="prop-1" asOfLocalDate="2026-10-08" onFirstInput={onFirstInput} />);
  return { ...utils, onFirstInput };
}

function input() {
  return screen.getByRole("textbox", { name: "La tua domanda per Mia" }) as HTMLTextAreaElement;
}

function form() {
  return screen.getByRole("form", { name: "Chiedi a Mia" });
}

/** The user's own message above the bar. */
function userMessage(container: HTMLElement) {
  return container.querySelector(".mia__user-message") as HTMLElement | null;
}

/** Mia's reply region (the live region under the user's message). */
function reply(container: HTMLElement) {
  return container.querySelector(".mia__reply") as HTMLElement | null;
}

/** `a` comes BEFORE `b` in the document. */
function before(a: Node, b: Node) {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

/** Sends `question` with Enter and waits for the (mocked) answer text to show. */
async function say(user: ReturnType<typeof userEvent.setup>, question: string, answer: string) {
  sendMock.mockResolvedValueOnce(answered(answer));
  await user.type(input(), `${question}{Enter}`);
  await screen.findByText(answer);
}

beforeEach(() => {
  sendMock.mockReset().mockResolvedValue(answered("Una risposta fondata."));
  listMock.mockReset().mockResolvedValue({ ok: true, data: { conversations: [] } });
  getMock.mockReset();
});

describe("MiaHome - the bar and its suggestions", () => {
  it("shows the approved placeholder and a labelled form (the placeholder is not the label)", () => {
    renderMia();

    expect(input().placeholder).toBe("Chiedi a Mia...");
    expect(form()).not.toBeNull();
    expect(screen.getByText("Chiedi a Mia o scegli una domanda")).not.toBeNull();
  });

  it("offers exactly the four approved suggested questions, in order, as real buttons", () => {
    renderMia();

    const list = screen.getByRole("list", { name: "Domande suggerite" });
    const buttons = within(list).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(QUESTIONS);
    for (const button of buttons) expect(button.getAttribute("type")).toBe("button");
  });

  it("renders NO microphone: no voice feature exists, so no fake control is drawn", () => {
    renderMia();

    expect(screen.queryByRole("button", { name: /microfon|dettatur|voice|vocale/iu })).toBeNull();
    expect(screen.queryByLabelText(/microfon|dettatur|voice|vocale/iu)).toBeNull();
  });

  it("limits the question to the backend's 1000 characters", () => {
    renderMia();

    expect(input().maxLength).toBe(1000);
  });

  it("has no exchange at all before the first question", () => {
    const { container } = renderMia();

    expect(userMessage(container)).toBeNull();
    expect(reply(container)).toBeNull();
  });
});

describe("MiaHome - suggestions fill the input and NEVER submit", () => {
  it("clicking a chip puts its text in the input, focuses it, and sends nothing", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.click(screen.getByRole("button", { name: QUESTIONS[1] as string }));

    expect(input().value).toBe(QUESTIONS[1]);
    expect(document.activeElement).toBe(input());
    expect(sendMock).not.toHaveBeenCalled();
    expect(userMessage(container)).toBeNull();
  });

  it("each of the four chips fills its own text", async () => {
    const user = userEvent.setup();
    renderMia();

    for (const question of QUESTIONS) {
      await user.click(screen.getByRole("button", { name: question }));
      expect(input().value).toBe(question);
    }
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("the user confirms with Enter, and then it behaves exactly like typed text", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.click(screen.getByRole("button", { name: QUESTIONS[0] as string }));

    await user.keyboard("{Enter}");

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf(QUESTIONS[0] as string));
    expect(input().value).toBe(""); // the bar is emptied...
    expect(userMessage(container)?.textContent).toContain(QUESTIONS[0]); // ...the question moved up
  });

  it("the arrow button confirms a suggestion too", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.click(screen.getByRole("button", { name: QUESTIONS[3] as string }));

    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf(QUESTIONS[3] as string));
    expect(input().value).toBe("");
    expect(userMessage(container)?.textContent).toContain(QUESTIONS[3]);
  });
});

describe("MiaHome - sending (Enter or the arrow)", () => {
  it("Enter sends the trimmed question with the property and the explicit business date", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "   Quali dati ha usato NINFA oggi?   {Enter}");

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf("Quali dati ha usato NINFA oggi?"));
  });

  it("the arrow button sends too", async () => {
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Ciao");

    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf("Ciao"));
  });

  it("an empty input sends nothing, and shows no arrow", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.click(input());
    await user.keyboard("{Enter}");

    expect(sendMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();
    expect(userMessage(container)).toBeNull();
  });

  it("whitespace alone sends nothing and creates no exchange", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "     {Enter}");

    expect(sendMock).not.toHaveBeenCalled();
    expect(userMessage(container)).toBeNull();
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();
  });

  it("the composer is a multi-line text area: Enter sends, Shift+Enter inserts a new line", async () => {
    const user = userEvent.setup();
    renderMia();
    expect(input().tagName).toBe("TEXTAREA");

    await user.type(input(), "Prima riga{Shift>}{Enter}{/Shift}Seconda riga");

    expect(sendMock).not.toHaveBeenCalled(); // Shift+Enter did NOT send
    expect(input().value).toBe("Prima riga\nSeconda riga");

    await user.keyboard("{Enter}");

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf("Prima riga\nSeconda riga"));
    expect(input().value).toBe(""); // the composer is emptied, no stray new line left behind
  });

  it("Enter never inserts a new line, not even when it has nothing to send", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "{Enter}{Enter}");
    expect(input().value).toBe("");
    await user.type(input(), "   {Enter}");
    expect(input().value).toBe("   ");
    expect(sendMock).not.toHaveBeenCalled();
  });

  it("Enter while composing text with an IME belongs to the composition and does not send", () => {
    renderMia();
    fireEvent.change(input(), { target: { value: "ciao" } });

    fireEvent.keyDown(input(), { key: "Enter", isComposing: true });

    expect(sendMock).not.toHaveBeenCalled();
    expect(input().value).toBe("ciao");
  });

  it("sends the multi-line text as the user wrote it (only the outer whitespace is trimmed)", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "  Prima{Shift>}{Enter}{/Shift}Seconda  ");
    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf("Prima\nSeconda"));
  });
});

/** A stand-in for layout, which jsdom does not do: every line of the text is 24px tall. */
function withLineLayout(run: () => Promise<void> | void) {
  const original = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "scrollHeight");
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return Math.max(1, this.value.split("\n").length) * 24;
    },
  });
  return Promise.resolve(run()).finally(() => {
    if (original) Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", original);
    else delete (HTMLTextAreaElement.prototype as unknown as Record<string, unknown>).scrollHeight;
  });
}

describe("MiaHome - the composer grows from 1 to 4 lines, then scrolls", () => {
  it("starts at one line and is a single row", () =>
    withLineLayout(() => {
      renderMia();
      expect(input().rows).toBe(1);
      expect(input().style.height).toBe("24px");
    }));

  it("grows line by line with Shift+Enter, up to four lines", () =>
    withLineLayout(async () => {
      const user = userEvent.setup();
      renderMia();

      await user.type(input(), "uno");
      expect(input().style.height).toBe("24px");
      await user.type(input(), "{Shift>}{Enter}{/Shift}due");
      expect(input().style.height).toBe("48px");
      await user.type(input(), "{Shift>}{Enter}{/Shift}tre");
      expect(input().style.height).toBe("72px");
      await user.type(input(), "{Shift>}{Enter}{/Shift}quattro");
      expect(input().style.height).toBe("96px");
      expect(input().style.overflowY).toBe("hidden"); // four lines still fit: no inner scroll yet
    }));

  it("stops at four lines and scrolls inside itself beyond that", () =>
    withLineLayout(async () => {
      const user = userEvent.setup();
      renderMia();

      await user.type(input(), "1{Shift>}{Enter}{/Shift}2{Shift>}{Enter}{/Shift}3{Shift>}{Enter}{/Shift}4");
      await user.type(input(), "{Shift>}{Enter}{/Shift}5{Shift>}{Enter}{/Shift}6");

      expect(input().style.height).toBe("96px"); // capped: four lines
      expect(input().style.overflowY).toBe("auto"); // the rest scrolls inside the composer
    }));

  it("shrinks back to one line when it is emptied by sending", () =>
    withLineLayout(async () => {
      const user = userEvent.setup();
      renderMia();
      await user.type(input(), "uno{Shift>}{Enter}{/Shift}due{Shift>}{Enter}{/Shift}tre");
      expect(input().style.height).toBe("72px");

      await user.keyboard("{Enter}");

      expect(input().value).toBe("");
      expect(input().style.height).toBe("24px");
    }));

  it("a suggested question fills it without sending, and it is still a normal field afterwards", () =>
    withLineLayout(async () => {
      const user = userEvent.setup();
      renderMia();

      await user.click(screen.getByRole("button", { name: QUESTIONS[2] as string }));

      expect(input().value).toBe(QUESTIONS[2]);
      expect(sendMock).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(input());
      await user.type(input(), " e altro");
      expect(input().value).toBe(`${QUESTIONS[2]} e altro`);
    }));
});

describe("MiaHome - the question leaves the bar and becomes the user's message", () => {
  it("empties the input IMMEDIATELY (before Mia has answered) and the placeholder is back", async () => {
    const request = pending();
    sendMock.mockReturnValue(request.promise);
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Ci sono altri problemi?{Enter}");

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(input().value).toBe(""); // still in flight, and already empty
    expect(input().placeholder).toBe("Chiedi a Mia...");
    request.resolve(answered("Fatto."));
    await screen.findByText("Fatto.");
    expect(input().value).toBe("");
  });

  it("shows the sent question above the bar as the user's own message - no 'LA TUA DOMANDA' card", async () => {
    const request = pending();
    sendMock.mockReturnValue(request.promise);
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Qual è la priorità più urgente oggi?{Enter}");

    const message = userMessage(container) as HTMLElement;
    expect(message.textContent).toContain("Qual è la priorità più urgente oggi?");
    expect(before(message, form())).toBe(true); // above the input
    expect(screen.queryByText("La tua domanda")).toBeNull(); // the old card label is gone
    // (the input keeps its own accessible label "La tua domanda per Mia"; only the old card label is gone)
    expect(container.textContent).not.toMatch(/la tua domanda(?! per mia)/iu);
    expect(container.querySelector(".mia__answer, .mia__asked")).toBeNull();
  });

  it("reads 'Hai chiesto:' to a screen reader before the question, without showing it twice", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ciao Mia{Enter}");

    const message = userMessage(container) as HTMLElement;
    expect(message.querySelector(".visually-hidden")?.textContent).toBe("Hai chiesto: ");
    expect(within(container).getAllByText("Ciao Mia")).toHaveLength(1);
  });

  it("the request is made with the question as submitted, not from what is in the bar afterwards", async () => {
    const request = pending();
    sendMock.mockReturnValue(request.promise);
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Prima domanda{Enter}");
    await user.type(input(), "bozza della prossima");

    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf("Prima domanda"));
    expect(input().value).toBe("bozza della prossima");
  });
});

describe("MiaHome - loading", () => {
  it("shows a discreet 'Mia sta analizzando…' UNDER the question, not blocking anything", async () => {
    sendMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ciao{Enter}");

    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Mia sta analizzando…");
    expect(before(userMessage(container) as HTMLElement, status)).toBe(true);
    expect(before(status, form())).toBe(true);
    // Mia is named, and the wording of the Decision Detail's own panel is not reused here.
    expect(within(reply(container) as HTMLElement).getByRole("heading", { name: "Mia" })).not.toBeNull();
    expect(container.textContent).not.toContain("questa decisione");
    expect(container.textContent).not.toMatch(/elaborando|ChatGPT|OpenAI|modello/iu);
  });

  it("makes the busy state perceptible: the arrow turns into a disabled spinner", async () => {
    sendMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ciao{Enter}");

    const busy = screen.getByRole("button", { name: "Mia sta analizzando…" }) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    expect(busy.querySelector(".mia__send-spinner")).not.toBeNull();
    expect(form().getAttribute("aria-busy")).toBe("true");
    expect(reply(container)?.getAttribute("aria-busy")).toBe("true");
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();
  });

  it("keeps the input usable (and focused): the keyboard is never taken away", async () => {
    sendMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Ciao{Enter}");

    expect(input().disabled).toBe(false);
    expect(document.activeElement).toBe(input()); // focus was NOT moved by the submit
  });

  it("locks the suggested questions while a request is in flight", async () => {
    sendMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Ciao{Enter}");

    for (const question of QUESTIONS) {
      expect((screen.getByRole("button", { name: question }) as HTMLButtonElement).disabled).toBe(true);
    }
  });
});

describe("MiaHome - exactly one request in flight", () => {
  it("blocks a double submit in the very same tick (Enter + click, key repeat)", async () => {
    sendMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Una sola volta");

    act(() => {
      fireEvent.submit(form());
      fireEvent.submit(form());
      fireEvent.submit(form());
    });

    expect(sendMock).toHaveBeenCalledTimes(1);
  });

  it("a draft typed while Mia answers cannot be sent until she has finished", async () => {
    const request = pending();
    sendMock.mockReturnValueOnce(request.promise);
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Prima{Enter}");
    await user.type(input(), "Seconda");

    await user.keyboard("{Enter}"); // ignored: one request at a time
    expect((screen.getByRole("button", { name: "Mia sta analizzando…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(input().value).toBe("Seconda"); // the draft is untouched

    sendMock.mockResolvedValueOnce(answered("Risposta alla seconda."));
    request.resolve(answered("Risposta alla prima."));
    await screen.findByText("Risposta alla prima.");

    const arrow = screen.getByRole("button", { name: "Invia la domanda a Mia" }) as HTMLButtonElement;
    expect(arrow.disabled).toBe(false); // sending is available again
    await user.click(arrow);
    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", sentOf("Seconda", "conv-1"));
  });
});

describe("MiaHome - focus stays with the user", () => {
  it("pressing the arrow with the mouse leaves the focus in the input", async () => {
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Ciao");

    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(document.activeElement).toBe(input());
    await screen.findByText("Una risposta fondata.");
    expect(document.activeElement).toBe(input());
  });

  it("activating the arrow from the keyboard brings the focus back to the input", async () => {
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Ciao");
    await user.tab(); // onto the arrow
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    await user.keyboard("{Enter}");

    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(input());
  });

  it("Riprova hands the focus back to the input as well", async () => {
    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Al momento non riesco a completare l'analisi con Mia.");

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(document.activeElement).toBe(input());
    await screen.findByText("Una risposta fondata.");
  });
});

describe("MiaHome - Mia's reply", () => {
  it("appears BELOW the submitted question, under Mia's name, as open text (not a boxed card)", async () => {
    sendMock.mockResolvedValue(answered("Hai una decisione aperta.", ["Costi non analizzati."]));
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ci sono altri problemi?{Enter}");

    const text = await screen.findByText("Hai una decisione aperta.");
    expect(before(userMessage(container) as HTMLElement, text)).toBe(true);
    expect(before(text, form())).toBe(true);
    const region = reply(container) as HTMLElement;
    expect(within(region).getByRole("heading", { level: 2, name: "Mia" })).not.toBeNull();
    expect(within(region).getByText("Da tenere presente")).not.toBeNull();
    expect(within(region).getByText("Costi non analizzati.")).not.toBeNull();
    expect(container.querySelector(".mia__answer")).toBeNull();
  });

  it("no longer uses the 'Risposta di Mia' heading, loading or answered", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(screen.queryByRole("heading", { name: "Risposta di Mia" })).toBeNull();
    expect(container.textContent).not.toContain("Risposta di Mia");
  });

  it("omits the limitations block when there are none", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(screen.queryByText("Da tenere presente")).toBeNull();
  });

  it("is the polite live region (announced), and does not wrap the sent question or the bar", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    const region = reply(container) as HTMLElement;
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.contains(userMessage(container))).toBe(false);
    expect(region.contains(form())).toBe(false);
  });

  it("leaves the keyboard where it was: still in the input after the answer, ready for the next question", async () => {
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Prima{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(document.activeElement).toBe(input());
    await user.keyboard("Seconda");
    expect(input().value).toBe("Seconda");
  });
});

describe("MiaHome - a conversation, not a chat page", () => {
  it("a NEW question is ADDED under the previous exchange, which stays visible", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await say(user, "Prima?", "Prima risposta.");
    await say(user, "Seconda?", "Seconda risposta.");

    expect(screen.getByText("Prima risposta.")).not.toBeNull();
    expect(screen.getByText("Seconda risposta.")).not.toBeNull();
    const messages = Array.from(container.querySelectorAll(".mia__user-message"));
    expect(messages.map((message) => message.textContent)).toEqual([
      expect.stringContaining("Prima?"),
      expect.stringContaining("Seconda?"),
    ]);
    expect(container.querySelectorAll(".mia__reply")).toHaveLength(2);
    expect(before(messages[0] as Node, messages[1] as Node)).toBe(true); // oldest first
  });

  it("the first message starts a conversation; the next continues it BY ITS ID, never with a history", async () => {
    const user = userEvent.setup();
    renderMia();

    await say(user, "Qual è la priorità più urgente?", "La prima nell'ordine di NINFA.");
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", sentOf("Qual è la priorità più urgente?"));

    await say(user, "Perché?", "Perché i dati mostrano un pickup basso.");

    expect(sendMock).toHaveBeenLastCalledWith("prop-1", sentOf("Perché?", "conv-1"));
    // The wire contract: the text, the date, the conversation id and the screen hint - nothing else.
    for (const [, input] of sendMock.mock.calls as [string, Record<string, unknown>][]) {
      expect(Object.keys(input).sort()).toEqual(["asOfLocalDate", "conversationId", "message", "uiContext"]);
    }
  });

  it("a message that left no trace on the server (unavailable, refused) never sets a conversation", async () => {
    const user = userEvent.setup();
    renderMia();
    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    await user.type(input(), "Domanda persa{Enter}");
    await screen.findByText("Al momento non riesco a completare l'analisi con Mia.");
    sendMock.mockResolvedValueOnce({
      ok: true,
      data: {
        status: "REFUSED",
        answer: null,
        grounding_refs: [],
        limitations: [],
        conversation_id: null,
      },
    });
    await user.type(input(), "Abbassa il prezzo{Enter}");
    await screen.findByText("Mia non può rispondere a questa domanda.");

    await say(user, "Una domanda buona", "Una risposta buona.");

    expect(sendMock).toHaveBeenNthCalledWith(3, "prop-1", sentOf("Una domanda buona"));
  });

  it("keeps only the newest four exchanges on screen (the rest stay in the server's conversation)", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    for (const index of [1, 2, 3, 4, 5]) await say(user, `D${index}?`, `R${index}.`);

    const messages = Array.from(container.querySelectorAll(".mia__user-message")).map(
      (message) => message.textContent,
    );
    expect(messages).toHaveLength(4);
    expect(messages[0]).toContain("D2?");
    expect(messages[3]).toContain("D5?");
    expect(screen.queryByText("R1.")).toBeNull();
    // ...and the fifth message still continued the same conversation
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", sentOf("D5?", "conv-1"));
  });

  it("while the new question runs, the earlier answers stay and only the newest shows loading", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await say(user, "Prima?", "Prima risposta.");
    sendMock.mockReturnValueOnce(new Promise(() => undefined));

    await user.type(input(), "Seconda?{Enter}");

    expect(screen.getByText("Prima risposta.")).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Mia sta analizzando…");
    expect(container.querySelectorAll(".mia__thinking")).toHaveLength(1);
  });

  it("only the newest reply is the polite live region", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await say(user, "Prima?", "Prima risposta.");
    await say(user, "Seconda?", "Seconda risposta.");

    const replies = Array.from(container.querySelectorAll(".mia__reply"));
    expect(replies.map((region) => region.getAttribute("aria-live"))).toEqual([null, "polite"]);
    expect(container.querySelectorAll("[aria-live='polite']")).toHaveLength(1);
  });

  it("lives in a bounded, labelled area above the bar - not a message log", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await say(user, "Prima?", "Prima risposta.");

    const conversation = screen.getByRole("region", { name: "Conversazione con Mia" });
    expect(conversation.querySelector(".mia__conversation-scroll")).not.toBeNull(); // scrolls inside
    expect(before(conversation, form())).toBe(true);
    expect(container.querySelector("[role='log'], .chat, .messages, .history")).toBeNull();
    expect(container.querySelectorAll("li:not(:has(button))")).toHaveLength(0); // no message list
  });

  it("starts the newest exchange at the top of the bounded area", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await say(user, "Prima?", "Prima risposta.");
    const area = container.querySelector(".mia__conversation-scroll") as HTMLElement;
    let scrollTop = 0;
    Object.defineProperty(area, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = value;
      },
    });
    const offsetTop = vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockReturnValue(240);

    try {
      await say(user, "Seconda?", "Seconda risposta.");
      expect(scrollTop).toBe(240); // the top of the newest exchange, not the end of its answer
    } finally {
      offsetTop.mockRestore();
    }
  });

  it("a retry re-sends the SAME message into the same conversation", async () => {
    const user = userEvent.setup();
    renderMia();
    await say(user, "Prima?", "Prima risposta.");
    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    await user.type(input(), "Seconda?{Enter}");
    await screen.findByText("Al momento non riesco a completare l'analisi con Mia.");
    sendMock.mockResolvedValueOnce(answered("Seconda risposta."));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    await screen.findByText("Seconda risposta.");
    expect(sendMock).toHaveBeenNthCalledWith(2, "prop-1", sentOf("Seconda?", "conv-1"));
    expect(sendMock).toHaveBeenNthCalledWith(3, "prop-1", sentOf("Seconda?", "conv-1"));
  });

  it("'Nuova conversazione' clears the exchanges and the next message starts a NEW conversation", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await say(user, "Prima?", "Prima risposta.");

    await user.click(screen.getByRole("button", { name: "Nuova conversazione" }));

    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Conversazione con Mia" })).toBeNull();
    expect(container.querySelector(".mia")?.getAttribute("data-answering")).toBe("false");
    expect(document.activeElement).toBe(input());
    await say(user, "Nuova?", "Nuova risposta.");
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", sentOf("Nuova?")); // no conversation id
  });

  it("'Nuova conversazione' is not available while Mia is answering", async () => {
    const user = userEvent.setup();
    renderMia();
    sendMock.mockReturnValueOnce(new Promise(() => undefined));
    await user.type(input(), "Ciao{Enter}");

    expect((screen.getByRole("button", { name: "Nuova conversazione" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("a different property is a different conversation; a different business date is not", async () => {
    const user = userEvent.setup();
    const { container, rerender, onFirstInput } = renderMia();
    await say(user, "Prima?", "Prima risposta.");
    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(1);

    // the same property on another business date: the conversation goes on, the date is just sent
    rerender(<MiaHome propertyId="prop-1" asOfLocalDate="2026-10-09" onFirstInput={onFirstInput} />);
    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(1);
    sendMock.mockResolvedValueOnce(answered("Domani."));
    await user.type(input(), "E domani?{Enter}");
    await screen.findByText("Domani.");
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", {
      ...sentOf("E domani?", "conv-1"),
      asOfLocalDate: "2026-10-09",
    });

    rerender(<MiaHome propertyId="prop-2" asOfLocalDate="2026-10-09" onFirstInput={onFirstInput} />);

    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(0);
    sendMock.mockResolvedValueOnce(answered("Risposta nuova."));
    await user.type(input(), "Altra?{Enter}");
    await screen.findByText("Risposta nuova.");
    expect(sendMock).toHaveBeenLastCalledWith("prop-2", {
      ...sentOf("Altra?"),
      asOfLocalDate: "2026-10-09",
    });
  });

  it("an answer that lands after the property changed is ignored", async () => {
    const stale = pending();
    sendMock.mockReturnValueOnce(stale.promise);
    const user = userEvent.setup();
    const { container, rerender, onFirstInput } = renderMia();
    await user.type(input(), "Lenta?{Enter}");

    rerender(<MiaHome propertyId="prop-2" asOfLocalDate="2026-10-08" onFirstInput={onFirstInput} />);
    stale.resolve(answered("Risposta tardiva della proprietà vecchia."));
    await act(async () => undefined);

    expect(screen.queryByText("Risposta tardiva della proprietà vecchia.")).toBeNull();
    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(0);
    // and the new property is not blocked by the stale request
    sendMock.mockResolvedValueOnce(answered("Subito."));
    await user.type(input(), "Ora?{Enter}");
    await screen.findByText("Subito.");
  });

  it("still sends one request at a time, however many exchanges there are", async () => {
    const user = userEvent.setup();
    renderMia();
    await say(user, "Prima?", "Prima risposta.");
    sendMock.mockReturnValueOnce(new Promise(() => undefined));
    await user.type(input(), "Seconda?{Enter}");

    await user.type(input(), "Terza?{Enter}");

    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(input().value).toBe("Terza?");
  });
});

describe("MiaHome - the conversation comes back from the server", () => {
  const STORED = {
    id: "conv-9",
    title: "Perché venerdì è debole?",
    updated_at: "2026-10-08T09:00:00Z",
    messages: [
      { role: "user", content: "Perché venerdì è debole?", created_at: "2026-10-08T08:59:00Z", limitations: [] },
      {
        role: "assistant",
        content: "Perché le prenotazioni per venerdì sono poche.",
        created_at: "2026-10-08T09:00:00Z",
        status: "ANSWERED",
        limitations: ["Solo prenotazioni attuali."],
      },
    ],
  };

  function storedConversationExists() {
    listMock.mockResolvedValue({
      ok: true,
      data: {
        conversations: [{ id: "conv-9", title: STORED.title, updated_at: STORED.updated_at, message_count: 2 }],
      },
    });
    getMock.mockResolvedValue({ ok: true, data: STORED });
  }

  it("restores the latest conversation on mount and CONTINUES it with its id", async () => {
    storedConversationExists();
    const user = userEvent.setup();
    const { container } = renderMia();

    expect(await screen.findByText("Perché le prenotazioni per venerdì sono poche.")).not.toBeNull();
    expect(userMessage(container)?.textContent).toContain("Perché venerdì è debole?");
    expect(screen.getByText("Solo prenotazioni attuali.")).not.toBeNull();
    expect(listMock).toHaveBeenCalledWith("prop-1");
    expect(getMock).toHaveBeenCalledWith("prop-1", "conv-9");
    expect(container.querySelector(".mia")?.getAttribute("data-answering")).toBe("true");

    sendMock.mockResolvedValueOnce(answered("E sabato?", [], "conv-9"));
    await user.type(input(), "E sabato?{Enter}");
    await screen.findAllByText("E sabato?");
    expect(sendMock).toHaveBeenCalledWith("prop-1", sentOf("E sabato?", "conv-9"));
  });

  it("restoring does not count as the person typing (the logo transition does not start)", async () => {
    storedConversationExists();
    const { onFirstInput } = renderMia();

    await screen.findByText("Perché le prenotazioni per venerdì sono poche.");

    expect(onFirstInput).not.toHaveBeenCalled();
  });

  it("shows nothing when there is no stored conversation, or when it cannot be read", async () => {
    const { container } = renderMia();
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(0);

    listMock.mockResolvedValue({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const second = render(<MiaHome propertyId="prop-3" asOfLocalDate="2026-10-08" onFirstInput={vi.fn()} />);
    await waitFor(() => expect(listMock).toHaveBeenCalledWith("prop-3"));
    expect(second.container.querySelectorAll(".mia__exchange")).toHaveLength(0);
    expect(screen.queryByRole("alert")).toBeNull(); // a failed restore is silent
  });

  it("never replaces what the person already sent with a conversation that arrives late", async () => {
    const late = pending();
    listMock.mockReturnValue(late.promise);
    const user = userEvent.setup();
    renderMia();
    await say(user, "Subito?", "Risposta subito.");

    late.resolve({
      ok: true,
      data: { conversations: [{ id: "conv-9", title: "t", updated_at: STORED.updated_at, message_count: 2 }] },
    });
    getMock.mockResolvedValue({ ok: true, data: STORED });
    await act(async () => undefined);

    expect(screen.getByText("Risposta subito.")).not.toBeNull();
    expect(screen.queryByText("Perché le prenotazioni per venerdì sono poche.")).toBeNull();
  });

  it("replaces a conversation the server no longer has with a new one, once, without an error", async () => {
    storedConversationExists();
    const user = userEvent.setup();
    renderMia();
    await screen.findByText("Perché le prenotazioni per venerdì sono poche.");
    sendMock
      .mockResolvedValueOnce({ ok: false, status: 404, code: "CONVERSATION_NOT_FOUND", message: "x" })
      .mockResolvedValueOnce(answered("Una nuova risposta.", [], "conv-new"));

    await user.type(input(), "E sabato?{Enter}");

    expect(await screen.findByText("Una nuova risposta.")).not.toBeNull();
    expect(sendMock).toHaveBeenNthCalledWith(1, "prop-1", sentOf("E sabato?", "conv-9"));
    expect(sendMock).toHaveBeenNthCalledWith(2, "prop-1", sentOf("E sabato?"));
    expect(screen.queryByText("Al momento non riesco a completare l'analisi con Mia.")).toBeNull();
  });
});

describe("MiaHome - page-aware: the screen's hint travels with the message", () => {
  function Publisher({ state }: { state: PageState }) {
    usePublishPage(state);
    return null;
  }

  it("sends the context the screen published, at the moment of sending, and nothing else", async () => {
    const user = userEvent.setup();
    render(
      <PageContextProvider>
        <Publisher state={{ route: PAGE_ROUTES.dati, section: "costs", periodDays: 7 }} />
        <MiaHome propertyId="prop-1" asOfLocalDate="2026-10-08" onFirstInput={vi.fn()} />
      </PageContextProvider>,
    );

    await user.type(input(), "Perché è così alto?{Enter}");

    expect(sendMock).toHaveBeenCalledWith("prop-1", {
      ...sentOf("Perché è così alto?"),
      uiContext: { route: "/dati", section: "costs", period_days: 7 },
    });
  });

  it("follows the screen: a new publication is what the NEXT message carries", async () => {
    const user = userEvent.setup();
    const view = (state: PageState) => (
      <PageContextProvider>
        <Publisher state={state} />
        <MiaHome propertyId="prop-1" asOfLocalDate="2026-10-08" onFirstInput={vi.fn()} />
      </PageContextProvider>
    );
    const { rerender } = render(view({ route: PAGE_ROUTES.dati, section: "costs", periodDays: 30 }));
    await user.type(input(), "Prima?{Enter}");
    await screen.findByText("Una risposta fondata.");

    rerender(view({ route: PAGE_ROUTES.dati, section: "labor", periodDays: 30 }));
    await user.type(input(), "E qui?{Enter}");

    await waitFor(() => expect(sendMock).toHaveBeenCalledTimes(2));
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", {
      ...sentOf("E qui?", "conv-1"),
      uiContext: { route: "/dati", section: "labor", period_days: 30 },
    });
  });
});

describe("MiaHome - every answer status keeps the sent question visible", () => {
  async function ask(response: unknown, question = "La mia domanda") {
    sendMock.mockResolvedValue(response);
    const user = userEvent.setup();
    const utils = renderMia();
    await user.type(input(), `${question}{Enter}`);
    return { user, ...utils };
  }

  it("ANSWERED", async () => {
    const { container } = await ask(answered("Risposta piena."));

    expect(await screen.findByText("Risposta piena.")).not.toBeNull();
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
  });

  it("INSUFFICIENT_CONTEXT shows Mia's honest explanation, never an invented answer", async () => {
    const { container } = await ask({
      ok: true,
      data: {
        status: "INSUFFICIENT_CONTEXT",
        answer: "L'analisi di oggi non è ancora disponibile.",
        grounding_refs: [],
        limitations: ["Nessuna analisi completata per oggi."],
      },
    });

    // Mia's own, specific explanation is the answer: it stands alone, with no generic
    // "non ha abbastanza informazioni" line put in front of it.
    expect(await screen.findByText("L'analisi di oggi non è ancora disponibile.")).not.toBeNull();
    expect(
      screen.queryByText(
        "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
      ),
    ).toBeNull();
    expect(screen.getByText("Nessuna analisi completata per oggi.")).not.toBeNull();
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
  });

  it("INSUFFICIENT_CONTEXT without an answer text still reads cleanly", async () => {
    await ask({
      ok: true,
      data: { status: "INSUFFICIENT_CONTEXT", answer: null, grounding_refs: [], limitations: [], conversation_id: null },
    });
    expect(
      await screen.findByText(
        "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
      ),
    ).not.toBeNull();
    // the generic hint belongs to this fallback only
    expect(
      screen.getByText(
        "Prova a formulare la domanda in modo diverso oppure apri le decisioni di oggi per i dettagli.",
      ),
    ).not.toBeNull();
  });

  it("ANSWERED renders short paragraphs and a real list for several decisions", async () => {
    const { container } = await ask(
      answered(
        [
          "Sì, oltre alla prima NINFA ha rilevato anche:",
          "- Rischio occupazione (Ricavi), data del soggiorno 22 agosto",
          "- Dipendenza OTA (Distribuzione)",
          "",
          "Non sono state analizzate le aree: Costi, Personale.",
        ].join("\n"),
      ),
    );

    expect(await screen.findByText("Sì, oltre alla prima NINFA ha rilevato anche:")).not.toBeNull();
    const items = Array.from(reply(container)?.querySelectorAll(".mia__reply-list > li") ?? []);
    expect(items.map((item) => item.textContent)).toEqual([
      "Rischio occupazione (Ricavi), data del soggiorno 22 agosto",
      "Dipendenza OTA (Distribuzione)",
    ]);
    expect(reply(container)?.querySelectorAll("p.mia__reply-text")).toHaveLength(2);
    // the bullet marker is structure, never shown as a literal dash
    expect(reply(container)?.textContent).not.toContain("- Rischio");
  });

  it("a rich answer is shown whole - no word dropped, nothing interpreted as markup", async () => {
    const text = "**Non** è grassetto <b>né html</b>.\n\nSeconda parte con 7,50 camere.";
    const { container } = await ask(answered(text));

    await screen.findByText("Seconda parte con 7,50 camere.");
    expect(reply(container)?.querySelector("b, strong, em, a")).toBeNull();
    expect(reply(container)?.textContent).toContain("**Non** è grassetto <b>né html</b>.");
  });

  it("INSUFFICIENT_CONTEXT with an explanation shows it alone - no generic lead or hint around it", async () => {
    const { container } = await ask({
      ok: true,
      data: {
        status: "INSUFFICIENT_CONTEXT",
        answer: "Posso spiegarti:\n- la priorità di oggi\n- le altre decisioni",
        grounding_refs: [],
        limitations: [],
      },
    });

    await screen.findByText("Posso spiegarti:");
    expect(reply(container)?.querySelectorAll(".mia__reply-list > li")).toHaveLength(2);
    expect(reply(container)?.querySelector(".mia__reply-lead")).toBeNull();
    expect(reply(container)?.querySelector(".mia__note")).toBeNull();
  });

  it("REFUSED", async () => {
    const { container } = await ask({
      ok: true,
      data: { status: "REFUSED", answer: null, grounding_refs: [], limitations: ["Mia non esegue azioni."] },
    });

    expect(await screen.findByText("Mia non può rispondere a questa domanda.")).not.toBeNull();
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
    expect(within(reply(container) as HTMLElement).getByRole("heading", { name: "Mia" })).not.toBeNull();
  });

  it("UNAVAILABLE offers a manual retry, never retries by itself, and keeps the question", async () => {
    const { container } = await ask({
      ok: true,
      data: { status: "UNAVAILABLE", answer: null, grounding_refs: [], limitations: [], conversation_id: null },
    });

    expect(await screen.findByText("Al momento non riesco a completare l'analisi con Mia.")).not.toBeNull();
    expect(screen.getByRole("alert")).not.toBeNull();
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
    expect(sendMock).toHaveBeenCalledTimes(1); // no automatic retry
  });

  it("a network/API error shows one calm line and a manual retry - never the raw message", async () => {
    const { container } = await ask({ ok: false, status: 0, code: "NETWORK_ERROR", message: "offline" });

    expect(await screen.findByText("Al momento non riesco a completare l'analisi con Mia.")).not.toBeNull();
    expect(screen.queryByText("offline")).toBeNull();
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
    expect(sendMock).toHaveBeenCalledTimes(1);
  });

  it("every status renders INSIDE Mia's reply region, under the sent question", async () => {
    const statuses = [
      { status: "INSUFFICIENT_CONTEXT", answer: "x" },
      { status: "REFUSED", answer: null },
      { status: "UNAVAILABLE", answer: null },
    ];
    for (const entry of statuses) {
      const { container, unmount } = await ask({
        ok: true,
        data: { ...entry, grounding_refs: [], limitations: [], conversation_id: null },
      });
      await waitFor(() => expect(reply(container)?.querySelector(".mia__reply-body")?.textContent).toBeTruthy());
      expect(before(userMessage(container) as HTMLElement, reply(container) as HTMLElement)).toBe(true);
      unmount();
    }
  });
});

describe("MiaHome - retry", () => {
  it("re-sends the SAME submitted question as a fresh call, without retyping it", async () => {
    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Al momento non riesco a completare l'analisi con Mia.");
    expect(input().value).toBe(""); // nothing to retype: the bar is empty
    sendMock.mockResolvedValueOnce(answered("Ora funziona."));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(await screen.findByText("Ora funziona.")).not.toBeNull();
    expect(sendMock).toHaveBeenCalledTimes(2);
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", sentOf("La mia domanda"));
    expect(screen.queryByText("Al momento non riesco a completare l'analisi con Mia.")).toBeNull();
    expect(container.querySelectorAll(".mia__user-message")).toHaveLength(1);
  });

  it("never touches a draft the user is typing meanwhile", async () => {
    sendMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Al momento non riesco a completare l'analisi con Mia.");
    await user.type(input(), "una bozza");

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    await screen.findByText("Una risposta fondata.");
    expect(sendMock).toHaveBeenLastCalledWith("prop-1", sentOf("La mia domanda"));
    expect(input().value).toBe("una bozza");
  });

  it("while the retry runs the question stays visible and the loading state shows again", async () => {
    sendMock.mockResolvedValueOnce({
      ok: true,
      data: { status: "UNAVAILABLE", answer: null, grounding_refs: [], limitations: [], conversation_id: null },
    });
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Al momento non riesco a completare l'analisi con Mia.");
    sendMock.mockReturnValueOnce(new Promise(() => undefined));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(screen.getByRole("status").textContent).toContain("Mia sta analizzando…");
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
  });
});

describe("MiaHome - state markers the stylesheet reads", () => {
  it("marks whether the input holds real text (short screens hide the suggestion panel once it does)", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    const root = container.querySelector(".mia") as HTMLElement;
    expect(root.getAttribute("data-has-text")).toBe("false");

    await user.type(input(), "   ");
    expect(root.getAttribute("data-has-text")).toBe("false"); // whitespace is not text

    await user.type(input(), "Ciao");
    expect(root.getAttribute("data-has-text")).toBe("true");
  });

  it("marks an open exchange (the suggestions step aside, the Home tightens a little)", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    const root = container.querySelector(".mia") as HTMLElement;
    expect(root.getAttribute("data-answering")).toBe("false");

    await user.type(input(), "Ciao{Enter}");

    await screen.findByText("Una risposta fondata.");
    expect(root.getAttribute("data-answering")).toBe("true");
    expect(root.getAttribute("data-has-text")).toBe("false"); // the bar was emptied by the send
  });
});

describe("MiaHome - first real input (what starts the logo transition)", () => {
  it("is NOT fired by focusing or clicking the input", async () => {
    const user = userEvent.setup();
    const { onFirstInput } = renderMia();

    await user.click(input());
    await user.tab();
    await user.click(input());

    expect(onFirstInput).not.toHaveBeenCalled();
  });

  it("is NOT fired by whitespace alone", async () => {
    const user = userEvent.setup();
    const { onFirstInput } = renderMia();

    await user.type(input(), "     ");

    expect(onFirstInput).not.toHaveBeenCalled();
  });

  it("is fired by the first real character", async () => {
    const user = userEvent.setup();
    const { onFirstInput } = renderMia();

    await user.type(input(), "C");

    expect(onFirstInput).toHaveBeenCalled();
  });

  it("is fired by pasted text", async () => {
    const user = userEvent.setup();
    const { onFirstInput } = renderMia();
    await user.click(input());

    await user.paste("Ci sono altri problemi?");

    expect(onFirstInput).toHaveBeenCalled();
    expect(input().value).toBe("Ci sono altri problemi?");
  });

  it("is fired when a suggested question fills the input (it is real text now)", async () => {
    const user = userEvent.setup();
    const { onFirstInput } = renderMia();

    await user.click(screen.getByRole("button", { name: QUESTIONS[2] as string }));

    expect(onFirstInput).toHaveBeenCalled();
  });

  it("is NOT fired again by clearing the input", async () => {
    const user = userEvent.setup();
    const { onFirstInput } = renderMia();
    await user.type(input(), "Ciao");
    onFirstInput.mockClear();

    await user.clear(input());

    expect(onFirstInput).not.toHaveBeenCalled();
  });
});

describe("MiaHome - naming", () => {
  it("calls the assistant Mia - never NINFA - on the whole surface, exchange included", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(container.textContent).not.toMatch(/Chiedi a NINFA|Risposta NINFA|Ask NINFA/u);
    expect(screen.getByRole("heading", { name: "Mia" })).not.toBeNull();
  });

  it("never renders a technical status code or raw JSON", async () => {
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(document.body.textContent).not.toMatch(/ANSWERED|INSUFFICIENT_CONTEXT|UNAVAILABLE|REFUSED|\{"/u);
  });
});
