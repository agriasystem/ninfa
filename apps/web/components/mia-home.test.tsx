// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
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

function renderMia(onFirstInput = vi.fn()) {
  const utils = render(<MiaHome propertyId="prop-1" asOfLocalDate="2026-10-08" onFirstInput={onFirstInput} />);
  return { ...utils, onFirstInput };
}

function input() {
  return screen.getByRole("textbox", { name: "La tua domanda per Mia" }) as HTMLInputElement;
}

beforeEach(() => {
  askMiaHomeMock.mockReset().mockResolvedValue(answered("Una risposta fondata."));
});

describe("MiaHome - the bar and its suggestions", () => {
  it("shows the approved placeholder and a labelled form (the placeholder is not the label)", () => {
    renderMia();

    expect(input().placeholder).toBe("Chiedi a Mia...");
    expect(screen.getByRole("form", { name: "Chiedi a Mia" })).not.toBeNull();
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

  it("names the assistant Mia - never 'Chiedi a NINFA' - everywhere on the surface", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Risposta di Mia");

    expect(container.textContent).not.toMatch(/Chiedi a NINFA|Risposta NINFA|Ask NINFA/u);
  });

  it("limits the question to the backend's 1000 characters", () => {
    renderMia();

    expect(input().maxLength).toBe(1000);
  });

  it("has no state at all before the first question: no answer surface, no history", () => {
    const { container } = renderMia();

    expect(container.querySelector(".mia__answer")).toBeNull();
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

  it("marks an in-flight or shown answer (the suggestions step aside, the Home stays clean)", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    const root = container.querySelector(".mia") as HTMLElement;
    expect(root.getAttribute("data-answering")).toBe("false");

    await user.type(input(), "Ciao{Enter}");

    await screen.findByText("Una risposta fondata.");
    expect(root.getAttribute("data-answering")).toBe("true");
  });
});

describe("MiaHome - suggestions fill the input and NEVER submit", () => {
  it("clicking a chip puts its text in the input, focuses it, and sends nothing", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.click(screen.getByRole("button", { name: QUESTIONS[1] as string }));

    expect(input().value).toBe(QUESTIONS[1]);
    expect(document.activeElement).toBe(input());
    expect(askMiaHomeMock).not.toHaveBeenCalled();
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

  it("the user confirms with Enter, and only then is the question sent", async () => {
    const user = userEvent.setup();
    renderMia();
    await user.click(screen.getByRole("button", { name: QUESTIONS[0] as string }));

    await user.keyboard("{Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", QUESTIONS[0]);
  });
});

describe("MiaHome - submitting", () => {
  it("sends the trimmed question with the property and the explicit business date", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "   Quali dati ha usato NINFA oggi?   {Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledWith("prop-1", "2026-10-08", "Quali dati ha usato NINFA oggi?");
  });

  it("does nothing for an empty or whitespace-only question", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "    {Enter}");

    expect(askMiaHomeMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();
  });

  it("shows an explicit send button only when there is text, and it submits", async () => {
    const user = userEvent.setup();
    renderMia();
    expect(screen.queryByRole("button", { name: "Invia la domanda a Mia" })).toBeNull();

    await user.type(input(), "Ciao");
    await user.click(screen.getByRole("button", { name: "Invia la domanda a Mia" }));

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
  });

  it("allows exactly ONE request in flight: Enter twice, input/chips/send locked meanwhile", async () => {
    let resolve: (value: unknown) => void = () => undefined;
    askMiaHomeMock.mockReturnValue(new Promise((r) => (resolve = r)));
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Prima domanda");
    await user.keyboard("{Enter}");
    await user.keyboard("{Enter}");

    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
    expect(input().disabled).toBe(true);
    for (const question of QUESTIONS) {
      expect((screen.getByRole("button", { name: question }) as HTMLButtonElement).disabled).toBe(true);
    }
    expect(screen.getByText("Mia sta analizzando la situazione di oggi…")).not.toBeNull();

    resolve(answered("Fatto."));
    expect(await screen.findByText("Fatto.")).not.toBeNull();
    expect(input().disabled).toBe(false);
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

  it("is NOT fired by clearing the input (the caller never reverses anything)", async () => {
    const user = userEvent.setup();
    const { onFirstInput } = renderMia();
    await user.type(input(), "Ciao");
    onFirstInput.mockClear();

    await user.clear(input());

    expect(onFirstInput).not.toHaveBeenCalled();
  });
});

describe("MiaHome - one question, one answer (no chat)", () => {
  it("shows the answer under 'Risposta di Mia', with the question it answers", async () => {
    askMiaHomeMock.mockResolvedValue(answered("Hai una decisione aperta.", ["Costi non analizzati."]));
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Ci sono altri problemi?{Enter}");

    expect(await screen.findByRole("heading", { name: "Risposta di Mia" })).not.toBeNull();
    expect(screen.getByText("Hai una decisione aperta.")).not.toBeNull();
    expect(screen.getByText("Da tenere presente")).not.toBeNull();
    expect(screen.getByText("Costi non analizzati.")).not.toBeNull();
    expect(screen.getByText("La tua domanda")).not.toBeNull();
    expect(screen.getAllByText("Ci sono altri problemi?").length).toBeGreaterThan(0);
  });

  it("omits the limitations block when there are none", async () => {
    const user = userEvent.setup();
    renderMia();

    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(screen.queryByText("Da tenere presente")).toBeNull();
  });

  it("a NEW question REPLACES the previous answer - never a growing list", async () => {
    askMiaHomeMock
      .mockResolvedValueOnce(answered("Prima risposta."))
      .mockResolvedValueOnce(answered("Seconda risposta."));
    const user = userEvent.setup();
    const { container } = renderMia();

    await user.type(input(), "Prima?{Enter}");
    await screen.findByText("Prima risposta.");
    await user.clear(input());
    await user.type(input(), "Seconda?{Enter}");
    await screen.findByText("Seconda risposta.");

    expect(screen.queryByText("Prima risposta.")).toBeNull();
    expect(screen.getAllByRole("heading", { name: "Risposta di Mia" })).toHaveLength(1);
    expect(container.querySelectorAll(".mia__answer")).toHaveLength(1);
    expect(screen.getByText("Seconda?", { selector: ".mia__asked-text" })).not.toBeNull();
    expect(screen.queryByText("Prima?", { selector: ".mia__asked-text" })).toBeNull();
  });

  it("keeps no message list, bubbles, roles or history anywhere", async () => {
    const user = userEvent.setup();
    const { container } = renderMia();
    await user.type(input(), "Ciao{Enter}");
    await screen.findByText("Una risposta fondata.");

    expect(container.querySelector("[role='log'], .chat, .message, .bubble")).toBeNull();
    expect(container.querySelectorAll("li:not(:has(button))")).toHaveLength(0);
  });
});

describe("MiaHome - every answer status", () => {
  async function ask(response: unknown) {
    askMiaHomeMock.mockResolvedValue(response);
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "Domanda{Enter}");
    return user;
  }

  it("ANSWERED", async () => {
    await ask(answered("Risposta piena."));
    expect(await screen.findByText("Risposta piena.")).not.toBeNull();
  });

  it("INSUFFICIENT_CONTEXT shows Mia's honest explanation, never an invented answer", async () => {
    await ask({
      ok: true,
      data: {
        status: "INSUFFICIENT_CONTEXT",
        answer: "L'analisi di oggi non è ancora disponibile.",
        grounding_refs: [],
        limitations: ["Nessuna analisi completata per oggi."],
      },
    });

    expect(
      await screen.findByText(
        "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
      ),
    ).not.toBeNull();
    expect(screen.getByText("L'analisi di oggi non è ancora disponibile.")).not.toBeNull();
    expect(screen.getByText("Nessuna analisi completata per oggi.")).not.toBeNull();
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
  });

  it("REFUSED", async () => {
    await ask({
      ok: true,
      data: { status: "REFUSED", answer: null, grounding_refs: [], limitations: ["Mia non esegue azioni."] },
    });
    expect(await screen.findByText("Mia non può rispondere a questa domanda.")).not.toBeNull();
  });

  it("UNAVAILABLE offers a manual retry and never retries by itself", async () => {
    await ask({
      ok: true,
      data: { status: "UNAVAILABLE", answer: null, grounding_refs: [], limitations: [] },
    });

    expect(await screen.findByText("Mia non è disponibile in questo momento.")).not.toBeNull();
    expect(screen.getByRole("alert")).not.toBeNull();
    expect(askMiaHomeMock).toHaveBeenCalledTimes(1); // no automatic retry
  });

  it("a network/API error shows one calm line and a manual retry", async () => {
    await ask({ ok: false, status: 0, code: "NETWORK_ERROR", message: "offline" });

    expect(await screen.findByText("Non è stato possibile ottenere una risposta da Mia.")).not.toBeNull();
    expect(screen.queryByText("offline")).toBeNull(); // never a raw backend message
    expect(askMiaHomeMock).toHaveBeenCalledTimes(1);
  });

  it("Riprova re-sends the SAME question as a fresh, explicit call", async () => {
    askMiaHomeMock.mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "x" });
    const user = userEvent.setup();
    renderMia();
    await user.type(input(), "La mia domanda{Enter}");
    await screen.findByText("Non è stato possibile ottenere una risposta da Mia.");
    askMiaHomeMock.mockResolvedValueOnce(answered("Ora funziona."));

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(await screen.findByText("Ora funziona.")).not.toBeNull();
    expect(askMiaHomeMock).toHaveBeenCalledTimes(2);
    expect(askMiaHomeMock).toHaveBeenLastCalledWith("prop-1", "2026-10-08", "La mia domanda");
    expect(screen.queryByText("Non è stato possibile ottenere una risposta da Mia.")).toBeNull();
  });

  it("never renders a technical status code or raw JSON", async () => {
    await ask(answered("Una risposta."));
    await screen.findByText("Una risposta.");

    await waitFor(() => {
      expect(document.body.textContent).not.toMatch(/ANSWERED|INSUFFICIENT_CONTEXT|UNAVAILABLE|REFUSED|\{"/u);
    });
  });
});
