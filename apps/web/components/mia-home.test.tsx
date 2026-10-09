// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AskResponse } from "@ninfa/contracts";

import { MiaHome } from "./mia-home";

const askMiaHomeMock = vi.fn();

vi.mock("@/lib/api/ask-ninfa", () => ({
  askMiaHome: (...args: unknown[]) => askMiaHomeMock(...args),
}));

const QUESTIONS = [
  "Ci sono altri problemi oltre a questo?",
  "Qual è la priorità più urgente oggi?",
  "Quale decisione ha l'impatto economico più alto?",
  "Quali dati ha usato NINFA oggi?",
];

function answered(answer: string, limitations: string[] = []): { ok: true; data: AskResponse } {
  return { ok: true, data: { status: "ANSWERED", answer, grounding_refs: [], limitations } };
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

beforeEach(() => {
  askMiaHomeMock.mockReset().mockResolvedValue(answered("Una risposta fondata."));
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
    expect(askMiaHomeMock).not.toHaveBeenCalled();
    expect(userMessage(container)).toBeNull();
  });

  it("each of the four chips fills its own text", async () => {
    const user = userEvent.setup();
    renderMia();

    for (const question of QUESTIONS) {
      await user.click(screen.getByRole("button", { name: question }));
      expect(input().value).toBe(question);
    }
    expect(askMiaHomeMock).not.toHaveBeenCalled();
  });

  it("the user confirms with Enter, and then it behaves exactly like typed text", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.click(screen.getByRole("button", { name: QUESTIONS[0] as string }));

    await user.keyboard("{Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", QUESTIONS[0], []);
    expect(input().value).toBe(""); // the bar is emptied...
    expect(userMessage(container)?.textContent).toContain(QUESTIONS[0]); // ...the question moved up
  });

  it("the arrow button confirms a suggestion too", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.click(screen.getByRole("button", { name: QUESTIONS[3] as string }));

    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", QUESTIONS[3], []);
    expect(input().value).toBe("");
    expect(userMessage(container)?.textContent).toContain(QUESTIONS[3]);
  });
});

describe("MiaHome - sending (Enter or the arrow)", () => {
  it("Enter sends the trimmed question with the property and the explicit business date", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "   Quali dati ha usato NINFA oggi?   {Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", "Quali dati ha usato NINFA oggi?", []);
  });

  it("the arrow button sends too", async () => {
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Ciao");

    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", "Ciao", []);
  });

  it("an empty input sends nothing, and shows no arrow", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.click(input());
    await user.keyboard("{Enter}");

    expect(askMiaHomeMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();
    expect(userMessage(container)).toBeNull();
  });

  it("whitespace alone sends nothing and creates no exchange", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "     {Enter}");

    expect(askMiaHomeMock).not.toHaveBeenCalled();
    expect(userMessage(container)).toBeNull();
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();
  });

  it("the composer is a multi-line text area: Enter sends, Shift+Enter inserts a new line", async () => {
    const user = userEvent.setup();
    renderMia();
    expect(input().tagName).toBe("TEXTAREA");

    await user.type(input(), "Prima riga{Shift>}{Enter}{/Shift}Seconda riga");

    expect(askMiaHomeMock).not.toHaveBeenCalled(); // Shift+Enter did NOT send
    expect(input().value).toBe("Prima riga\nSeconda riga");

    await user.keyboard("{Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", "Prima riga\nSeconda riga", []);
    expect(input().value).toBe(""); // the composer is emptied, no stray new line left behind
  });

  it("Enter never inserts a new line, not even when it has nothing to send", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "{Enter}{Enter}");
    expect(input().value).toBe("");
    await user.type(input(), "   {Enter}");
    expect(input().value).toBe("   ");
    expect(askMiaHomeMock).not.toHaveBeenCalled();
  });

  it("Enter while composing text with an IME belongs to the composition and does not send", () => {
    renderMia();
    fireEvent.change(input(), { target: { value: "ciao" } });

    fireEvent.keyDown(input(), { key: "Enter", isComposing: true });

    expect(askMiaHomeMock).not.toHaveBeenCalled();
    expect(input().value).toBe("ciao");
  });

  it("sends the multi-line text as the user wrote it (only the outer whitespace is trimmed)", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "  Prima{Shift>}{Enter}{/Shift}Seconda  ");
    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", "Prima\nSeconda", []);
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
      expect(askMiaHomeMock).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(input());
      await user.type(input(), " e altro");
      expect(input().value).toBe(`${QUESTIONS[2]} e altro`);
    }));
});

describe("MiaHome - the question leaves the bar and becomes the user's message", () => {
  it("empties the input IMMEDIATELY (before Mia has answered) and the placeholder is back", async () => {
    const request = pending();
    askMiaHomeMock.mockReturnValue(request.promise);
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Ci sono altri problemi?{Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(input().value).toBe(""); // still in flight, and already empty
    expect(input().placeholder).toBe("Chiedi a Mia...");
    request.resolve(answered("Fatto."));
    await screen.findByText("Fatto.");
    expect(input().value).toBe("");
  });

  it("shows the sent question above the bar as the user's own message - no 'LA TUA DOMANDA' card", async () => {
    const request = pending();
    askMiaHomeMock.mockReturnValue(request.promise);
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
    askMiaHomeMock.mockReturnValue(request.promise);
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Prima domanda{Enter}");
    await user.type(input(), "bozza della prossima");

    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", "Prima domanda", []);
    expect(input().value).toBe("bozza della prossima");
  });
});

describe("MiaHome - loading", () => {
  it("shows a discreet 'Mia sta elaborando…' UNDER the question, not blocking anything", async () => {
    askMiaHomeMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ciao{Enter}");

    const status = screen.getByRole("status");
    expect(status.textContent).toContain("Mia sta elaborando…");
    expect(before(userMessage(container) as HTMLElement, status)).toBe(true);
    expect(before(status, form())).toBe(true);
    // Mia is named, and the old wording is gone.
    expect(within(reply(container) as HTMLElement).getByRole("heading", { name: "Mia" })).not.toBeNull();
    expect(container.textContent).not.toContain("Mia sta analizzando");
  });

  it("makes the busy state perceptible: the arrow turns into a disabled spinner", async () => {
    askMiaHomeMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Ciao{Enter}");

    const busy = screen.getByRole("button", { name: "Mia sta elaborando…" }) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    expect(busy.querySelector(".mia__send-spinner")).not.toBeNull();
    expect(form().getAttribute("aria-busy")).toBe("true");
    expect(reply(container)?.getAttribute("aria-busy")).toBe("true");
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();
  });

  it("keeps the input usable (and focused): the keyboard is never taken away", async () => {
    askMiaHomeMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Ciao{Enter}");

    expect(input().disabled).toBe(false);
    expect(document.activeElement).toBe(input()); // focus was NOT moved by the submit
  });

  it("locks the suggested questions while a request is in flight", async () => {
    askMiaHomeMock.mockReturnValue(new Promise(() => undefined));
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
    askMiaHomeMock.mockReturnValue(new Promise(() => undefined));
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Una sola volta");

    act(() => {
      fireEvent.submit(form());
      fireEvent.submit(form());
      fireEvent.submit(form());
    });

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
  });

  it("a draft typed while Mia answers cannot be sent until she has finished", async () => {
    const request = pending();
    askMiaHomeMock.mockReturnValueOnce(request.promise);
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Prima{Enter}");
    await user.type(input(), "Seconda");

    await user.keyboard("{Enter}"); // ignored: one request at a time
    expect((screen.getByRole("button", { name: "Mia sta elaborando…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(input().value).toBe("Seconda"); // the draft is untouched

    askMiaHomeMock.mockResolvedValueOnce(answered("Risposta alla seconda."));
    request.resolve(answered("Risposta alla prima."));
    await screen.findByText("Risposta alla prima.");

    const arrow = screen.getByRole("button", { name: "Invia la domanda a Mia" }) as HTMLButtonElement;
    expect(arrow.disabled).toBe(false); // sending is available again
    await user.click(arrow);
    expect(askMiaHomeMock).toHaveBeenCalledTimes(2);
    expect(askMiaHomeMock).toHaveBeenLastCalledWith("prop-1", "2026-10-08", "Seconda", [
      { role: "user", content: "Prima" },
      { role: "assistant", content: "Risposta alla prima." },
    ]);
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

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(input());
  });

  it("Riprova hands the focus back to the input as well", async () => {
    askMiaHomeMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Non è stato possibile ottenere una risposta da Mia.");

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(document.activeElement).toBe(input());
    await screen.findByText("Una risposta fondata.");
  });
});

describe("MiaHome - Mia's reply", () => {
  it("appears BELOW the submitted question, under Mia's name, as open text (not a boxed card)", async () => {
    askMiaHomeMock.mockResolvedValue(answered("Hai una decisione aperta.", ["Costi non analizzati."]));
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

describe("MiaHome - a short conversation, not a chat page", () => {
  /** Sends `question` with Enter and waits for the (mocked) answer text to show. */
  async function say(user: ReturnType<typeof userEvent.setup>, question: string, answer: string) {
    askMiaHomeMock.mockResolvedValueOnce(answered(answer));
    await user.type(input(), `${question}{Enter}`);
    await screen.findByText(answer);
  }

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

  it("the first question carries no history; the next carries the exchange before it", async () => {
    const user = userEvent.setup();
    renderMia();

    await say(user, "Qual è la priorità più urgente?", "La prima nell'ordine di NINFA.");
    expect(askMiaHomeMock).toHaveBeenLastCalledWith(
      "prop-1",
      "2026-10-08",
      "Qual è la priorità più urgente?",
      [],
    );

    await say(user, "Perché?", "Perché i dati mostrano un pickup basso.");

    expect(askMiaHomeMock).toHaveBeenLastCalledWith("prop-1", "2026-10-08", "Perché?", [
      { role: "user", content: "Qual è la priorità più urgente?" },
      { role: "assistant", content: "La prima nell'ordine di NINFA." },
    ]);
  });

  it("the history is the answers as Mia wrote them (not the rendered list), oldest first", async () => {
    const user = userEvent.setup();
    renderMia();
    const listAnswer = "Sì, oltre alla prima:\n- Dipendenza OTA\n- Costo per camera";
    askMiaHomeMock.mockResolvedValueOnce(answered(listAnswer));
    await user.type(input(), "Altri problemi?{Enter}");
    await screen.findByText("Dipendenza OTA");

    await say(user, "Dimmi di più", "Ecco.");

    const [, , , history] = askMiaHomeMock.mock.calls[1] as [string, string, string, unknown];
    expect(history).toEqual([
      { role: "user", content: "Altri problemi?" },
      { role: "assistant", content: listAnswer },
    ]);
  });

  it("an exchange that failed, was refused or was unavailable is never part of the history", async () => {
    const user = userEvent.setup();
    renderMia();
    askMiaHomeMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    await user.type(input(), "Domanda persa{Enter}");
    await screen.findByText("Non è stato possibile ottenere una risposta da Mia.");
    askMiaHomeMock.mockResolvedValueOnce({
      ok: true,
      data: { status: "REFUSED", answer: null, grounding_refs: [], limitations: [] },
    });
    await user.type(input(), "Abbassa il prezzo{Enter}");
    await screen.findByText("Mia non può rispondere a questa domanda.");

    await say(user, "Una domanda buona", "Una risposta buona.");
    await say(user, "E poi?", "Poi basta.");

    expect(askMiaHomeMock).toHaveBeenNthCalledWith(3, "prop-1", "2026-10-08", "Una domanda buona", []);
    expect(askMiaHomeMock).toHaveBeenNthCalledWith(4, "prop-1", "2026-10-08", "E poi?", [
      { role: "user", content: "Una domanda buona" },
      { role: "assistant", content: "Una risposta buona." },
    ]);
  });

  it("keeps only the newest four exchanges, and the history is exactly what is still on screen", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();

    for (const index of [1, 2, 3, 4, 5]) await say(user, `D${index}?`, `R${index}.`);

    const messages = Array.from(container.querySelectorAll(".mia__user-message")).map(
      (message) => message.textContent,
    );
    expect(messages).toHaveLength(4);
    expect(messages[0]).toContain("D2?");
    expect(messages[3]).toContain("D5?");
    expect(screen.queryByText("R1.")).toBeNull(); // the oldest left the screen...
    const [, , , history] = askMiaHomeMock.mock.calls[4] as [string, string, string, unknown[]];
    expect(history).toEqual([
      { role: "user", content: "D2?" },
      { role: "assistant", content: "R2." },
      { role: "user", content: "D3?" },
      { role: "assistant", content: "R3." },
      { role: "user", content: "D4?" },
      { role: "assistant", content: "R4." },
    ]); // ...and out of what the model is told: three exchanges + the new question = four
    expect(history.length).toBeLessThanOrEqual(6);
  });

  it("while the new question runs, the earlier answers stay and only the newest shows loading", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await say(user, "Prima?", "Prima risposta.");
    askMiaHomeMock.mockReturnValueOnce(new Promise(() => undefined));

    await user.type(input(), "Seconda?{Enter}");

    expect(screen.getByText("Prima risposta.")).not.toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Mia sta elaborando…");
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

  it("a retry re-sends the SAME question with the history it originally had", async () => {
    const user = userEvent.setup();
    renderMia();
    await say(user, "Prima?", "Prima risposta.");
    askMiaHomeMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    await user.type(input(), "Seconda?{Enter}");
    await screen.findByText("Non è stato possibile ottenere una risposta da Mia.");
    askMiaHomeMock.mockResolvedValueOnce(answered("Seconda risposta."));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    await screen.findByText("Seconda risposta.");
    const expectedHistory = [
      { role: "user", content: "Prima?" },
      { role: "assistant", content: "Prima risposta." },
    ];
    expect(askMiaHomeMock).toHaveBeenNthCalledWith(2, "prop-1", "2026-10-08", "Seconda?", expectedHistory);
    expect(askMiaHomeMock).toHaveBeenNthCalledWith(3, "prop-1", "2026-10-08", "Seconda?", expectedHistory);
  });

  it("'Nuova conversazione' clears the exchanges and the next question carries no history", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await say(user, "Prima?", "Prima risposta.");

    await user.click(screen.getByRole("button", { name: "Nuova conversazione" }));

    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Conversazione con Mia" })).toBeNull();
    expect(container.querySelector(".mia")?.getAttribute("data-answering")).toBe("false");
    expect(document.activeElement).toBe(input());
    await say(user, "Nuova?", "Nuova risposta.");
    expect(askMiaHomeMock).toHaveBeenLastCalledWith("prop-1", "2026-10-08", "Nuova?", []);
  });

  it("'Nuova conversazione' is not available while Mia is answering", async () => {
    const user = userEvent.setup();
    renderMia();
    askMiaHomeMock.mockReturnValueOnce(new Promise(() => undefined));
    await user.type(input(), "Ciao{Enter}");

    expect((screen.getByRole("button", { name: "Nuova conversazione" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("a different property or business date starts a different conversation", async () => {
    const user = userEvent.setup();
    const { container, rerender, onFirstInput } = renderMia();
    await say(user, "Prima?", "Prima risposta.");
    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(1);

    rerender(<MiaHome propertyId="prop-2" asOfLocalDate="2026-10-08" onFirstInput={onFirstInput} />);

    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(0);
    askMiaHomeMock.mockResolvedValueOnce(answered("Risposta nuova."));
    await user.type(input(), "Altra?{Enter}");
    await screen.findByText("Risposta nuova.");
    expect(askMiaHomeMock).toHaveBeenLastCalledWith("prop-2", "2026-10-08", "Altra?", []);
  });

  it("an answer that lands after the conversation was reset is ignored", async () => {
    const stale = pending();
    askMiaHomeMock.mockReturnValueOnce(stale.promise);
    const user = userEvent.setup();
    const { container, rerender, onFirstInput } = renderMia();
    await user.type(input(), "Lenta?{Enter}");

    rerender(<MiaHome propertyId="prop-2" asOfLocalDate="2026-10-08" onFirstInput={onFirstInput} />);
    stale.resolve(answered("Risposta tardiva della proprietà vecchia."));
    await act(async () => undefined);

    expect(screen.queryByText("Risposta tardiva della proprietà vecchia.")).toBeNull();
    expect(container.querySelectorAll(".mia__exchange")).toHaveLength(0);
    // and the new property is not blocked by the stale request
    askMiaHomeMock.mockResolvedValueOnce(answered("Subito."));
    await user.type(input(), "Ora?{Enter}");
    await screen.findByText("Subito.");
  });

  it("still sends one request at a time, however many exchanges there are", async () => {
    const user = userEvent.setup();
    renderMia();
    await say(user, "Prima?", "Prima risposta.");
    askMiaHomeMock.mockReturnValueOnce(new Promise(() => undefined));
    await user.type(input(), "Seconda?{Enter}");

    await user.type(input(), "Terza?{Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledTimes(2);
    expect(input().value).toBe("Terza?");
  });
});

describe("MiaHome - every answer status keeps the sent question visible", () => {
  async function ask(response: unknown, question = "La mia domanda") {
    askMiaHomeMock.mockResolvedValue(response);
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
      data: { status: "INSUFFICIENT_CONTEXT", answer: null, grounding_refs: [], limitations: [] },
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
      data: { status: "UNAVAILABLE", answer: null, grounding_refs: [], limitations: [] },
    });

    expect(await screen.findByText("Mia non è disponibile in questo momento.")).not.toBeNull();
    expect(screen.getByRole("alert")).not.toBeNull();
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
    expect(askMiaHomeMock).toHaveBeenCalledTimes(1); // no automatic retry
  });

  it("a network/API error shows one calm line and a manual retry - never the raw message", async () => {
    const { container } = await ask({ ok: false, status: 0, code: "NETWORK_ERROR", message: "offline" });

    expect(await screen.findByText("Non è stato possibile ottenere una risposta da Mia.")).not.toBeNull();
    expect(screen.queryByText("offline")).toBeNull();
    expect(userMessage(container)?.textContent).toContain("La mia domanda");
    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
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
        data: { ...entry, grounding_refs: [], limitations: [] },
      });
      await waitFor(() => expect(reply(container)?.querySelector(".mia__reply-body")?.textContent).toBeTruthy());
      expect(before(userMessage(container) as HTMLElement, reply(container) as HTMLElement)).toBe(true);
      unmount();
    }
  });
});

describe("MiaHome - retry", () => {
  it("re-sends the SAME submitted question as a fresh call, without retyping it", async () => {
    askMiaHomeMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Non è stato possibile ottenere una risposta da Mia.");
    expect(input().value).toBe(""); // nothing to retype: the bar is empty
    askMiaHomeMock.mockResolvedValueOnce(answered("Ora funziona."));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(await screen.findByText("Ora funziona.")).not.toBeNull();
    expect(askMiaHomeMock).toHaveBeenCalledTimes(2);
    expect(askMiaHomeMock).toHaveBeenLastCalledWith("prop-1", "2026-10-08", "La mia domanda", []);
    expect(screen.queryByText("Non è stato possibile ottenere una risposta da Mia.")).toBeNull();
    expect(container.querySelectorAll(".mia__user-message")).toHaveLength(1);
  });

  it("never touches a draft the user is typing meanwhile", async () => {
    askMiaHomeMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Non è stato possibile ottenere una risposta da Mia.");
    await user.type(input(), "una bozza");

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    await screen.findByText("Una risposta fondata.");
    expect(askMiaHomeMock).toHaveBeenLastCalledWith("prop-1", "2026-10-08", "La mia domanda", []);
    expect(input().value).toBe("una bozza");
  });

  it("while the retry runs the question stays visible and the loading state shows again", async () => {
    askMiaHomeMock.mockResolvedValueOnce({
      ok: true,
      data: { status: "UNAVAILABLE", answer: null, grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Mia non è disponibile in questo momento.");
    askMiaHomeMock.mockReturnValueOnce(new Promise(() => undefined));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(screen.getByRole("status").textContent).toContain("Mia sta elaborando…");
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
