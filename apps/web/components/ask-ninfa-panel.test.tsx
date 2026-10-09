// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AskNinfaPanel } from "./ask-ninfa-panel";

const askNinfaMock = vi.fn();

vi.mock("@/lib/api/ask-ninfa", () => ({
  askNinfa: (...args: unknown[]) => askNinfaMock(...args),
}));

beforeEach(() => {
  askNinfaMock.mockReset();
});

function renderPanel(propertyId = "prop-1", decisionId = "dec-1") {
  return render(<AskNinfaPanel propertyId={propertyId} decisionId={decisionId} />);
}

async function askQuestion(user: ReturnType<typeof userEvent.setup>, question: string) {
  await user.type(screen.getByLabelText("La tua domanda"), question);
  await user.click(screen.getByRole("button", { name: "Chiedi a Mia" }));
}

describe("AskNinfaPanel - card and suggested questions", () => {
  it("renders the heading, supporting text and the three suggested question chips", () => {
    renderPanel();

    expect(screen.getByRole("heading", { name: "Chiedi a Mia" })).not.toBeNull();
    expect(
      screen.getByText("Approfondisci questa decisione usando i dati che NINFA ha già analizzato."),
    ).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Perché NINFA mi sta mostrando questa decisione?" }),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "Cosa significa questo scostamento?" })).not.toBeNull();
    expect(screen.getByRole("button", { name: "Cosa posso verificare?" })).not.toBeNull();
  });

  it("a suggested question populates the input WITHOUT submitting", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(
      screen.getByRole("button", { name: "Perché NINFA mi sta mostrando questa decisione?" }),
    );

    expect((screen.getByLabelText("La tua domanda") as HTMLInputElement).value).toBe(
      "Perché NINFA mi sta mostrando questa decisione?",
    );
    expect(askNinfaMock).not.toHaveBeenCalled();
  });

  it("suggested question chips are real buttons, never a link or a submit control", () => {
    renderPanel();

    const chip = screen.getByRole("button", { name: "Cosa posso verificare?" }) as HTMLButtonElement;
    expect(chip.type).toBe("button");
  });
});

describe("AskNinfaPanel - input and submit gating", () => {
  it("the submit button is disabled while the question is empty or whitespace-only", async () => {
    const user = userEvent.setup();
    renderPanel();

    const button = screen.getByRole("button", { name: "Chiedi a Mia" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    await user.type(screen.getByLabelText("La tua domanda"), "   ");
    expect(button.disabled).toBe(true);

    await user.type(screen.getByLabelText("La tua domanda"), "x");
    expect(button.disabled).toBe(false);
  });

  it("an empty question can never actually be sent (clicking a disabled button calls nothing)", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "Chiedi a Mia" }));

    expect(askNinfaMock).not.toHaveBeenCalled();
  });

  it("submit calls askNinfa with the exact propertyId/decisionId this panel was given", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: { status: "ANSWERED", answer: "Risposta.", grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    renderPanel("prop-77", "dec-99");

    await askQuestion(user, "Perché me lo mostri?");

    expect(askNinfaMock).toHaveBeenCalledWith("prop-77", "dec-99", "Perché me lo mostri?");
  });

  it("pressing Enter inside the question input submits the form (keyboard submit)", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: { status: "ANSWERED", answer: "Risposta.", grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByLabelText("La tua domanda"), "Perché me lo mostri?{Enter}");

    await waitFor(() => expect(askNinfaMock).toHaveBeenCalledOnce());
  });

  it("only one request is ever in flight: input and CTA disable during loading, blocking a duplicate", async () => {
    let resolveAsk!: (value: unknown) => void;
    askNinfaMock.mockReturnValue(new Promise((resolve) => (resolveAsk = resolve)));
    const user = userEvent.setup();
    renderPanel();

    await user.type(screen.getByLabelText("La tua domanda"), "Perché me lo mostri?");
    const button = screen.getByRole("button", { name: "Chiedi a Mia" });
    await user.click(button);

    const loadingButton = screen.getByRole("button", {
      name: "Mia sta analizzando questa decisione…",
    }) as HTMLButtonElement;
    expect(loadingButton.disabled).toBe(true);
    expect((screen.getByLabelText("La tua domanda") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("Mia sta analizzando questa decisione…", { selector: "p" })).not.toBeNull();

    // A second click on the (disabled) button must never trigger a second call.
    await user.click(loadingButton);
    expect(askNinfaMock).toHaveBeenCalledOnce();

    resolveAsk({
      ok: true,
      data: { status: "ANSWERED", answer: "Risposta.", grounding_refs: [], limitations: [] },
    });
    await screen.findByText("Risposta.");
  });
});

describe("AskNinfaPanel - ANSWERED", () => {
  it("shows the answer under a plain 'Risposta di Mia' heading", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: {
        status: "ANSWERED",
        answer: "Il pickup è sotto le attese per questa data.",
        grounding_refs: ["LATEST_FACTS"],
        limitations: [],
      },
    });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Perché me lo mostri?");

    expect(await screen.findByText("Risposta di Mia")).not.toBeNull();
    expect(screen.getByText("Il pickup è sotto le attese per questa data.")).not.toBeNull();
  });

  it("shows a discrete 'Da tenere presente' section when limitations are present", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: {
        status: "ANSWERED",
        answer: "Risposta.",
        grounding_refs: [],
        limitations: ["Stima indicativa, non un valore certo."],
      },
    });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Qual è l'impatto economico?");

    expect(await screen.findByText("Da tenere presente")).not.toBeNull();
    expect(screen.getByText("Stima indicativa, non un valore certo.")).not.toBeNull();
  });

  it("shows no limitations section at all when limitations is empty", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: { status: "ANSWERED", answer: "Risposta.", grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Perché me lo mostri?");

    await screen.findByText("Risposta.");
    expect(screen.queryByText("Da tenere presente")).toBeNull();
  });
});

describe("AskNinfaPanel - INSUFFICIENT_CONTEXT / UNAVAILABLE / REFUSED", () => {
  it("shows the documented INSUFFICIENT_CONTEXT copy, plus the real grounded answer when present", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: {
        status: "INSUFFICIENT_CONTEXT",
        answer: "Non posso stabilire di quanto ridurre il prezzo con i dati disponibili.",
        grounding_refs: [],
        limitations: [],
      },
    });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Di quanto devo abbassare il prezzo?");

    expect(
      await screen.findByText(
        "Mia non ha abbastanza informazioni per rispondere con affidabilità a questa domanda.",
      ),
    ).not.toBeNull();
    expect(
      screen.getByText("Non posso stabilire di quanto ridurre il prezzo con i dati disponibili."),
    ).not.toBeNull();
    expect(
      screen.getByText(
        "Prova a formulare la domanda in modo diverso oppure consulta i dati disponibili nella decisione.",
      ),
    ).not.toBeNull();
  });

  it("shows the documented UNAVAILABLE copy with a manual retry button", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: { status: "UNAVAILABLE", answer: null, grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Perché me lo mostri?");

    expect(
      await screen.findByText("Chiedi a Mia non è disponibile in questo momento."),
    ).not.toBeNull();
    expect(screen.getByText("Puoi riprovare manualmente.")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Riprova" })).not.toBeNull();
  });

  it("shows the documented, neutral REFUSED copy - no verbose safety/legal language", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: { status: "REFUSED", answer: null, grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Esegui questa azione");

    expect(
      await screen.findByText("Mia non può rispondere a questa domanda nel contesto della decisione."),
    ).not.toBeNull();
  });
});

describe("AskNinfaPanel - network/HTTP error and retry", () => {
  it("shows a generic, user-facing error (never the raw backend/network message)", async () => {
    askNinfaMock.mockResolvedValue({ ok: false, status: 0, code: "NETWORK_ERROR", message: "boom" });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Perché me lo mostri?");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Non è stato possibile ottenere una risposta da Mia.");
    expect(alert.textContent).not.toContain("boom");
  });

  it("retry happens ONLY on explicit user click - never automatically - and issues a fresh call", async () => {
    askNinfaMock
      .mockResolvedValueOnce({ ok: false, status: 0, code: "NETWORK_ERROR", message: "boom" })
      .mockResolvedValueOnce({
        ok: true,
        data: { status: "ANSWERED", answer: "Risposta dopo retry.", grounding_refs: [], limitations: [] },
      });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Perché me lo mostri?");
    await screen.findByRole("alert");
    expect(askNinfaMock).toHaveBeenCalledOnce(); // no automatic retry happened on its own

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(await screen.findByText("Risposta dopo retry.")).not.toBeNull();
    expect(askNinfaMock).toHaveBeenCalledTimes(2);
  });

  it("retry after UNAVAILABLE also issues a fresh, explicit API call", async () => {
    askNinfaMock
      .mockResolvedValueOnce({
        ok: true,
        data: { status: "UNAVAILABLE", answer: null, grounding_refs: [], limitations: [] },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { status: "ANSWERED", answer: "Ora funziona.", grounding_refs: [], limitations: [] },
      });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Perché me lo mostri?");
    await screen.findByRole("button", { name: "Riprova" });

    await user.click(screen.getByRole("button", { name: "Riprova" }));

    expect(await screen.findByText("Ora funziona.")).not.toBeNull();
    expect(askNinfaMock).toHaveBeenCalledTimes(2);
  });
});

describe("AskNinfaPanel - no chatbot aesthetic, no branding, no chat history", () => {
  it("never mentions the provider, model, or token usage anywhere in the DOM", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: { status: "ANSWERED", answer: "Risposta.", grounding_refs: ["LATEST_FACTS"], limitations: [] },
    });
    const user = userEvent.setup();
    const { container } = renderPanel();

    await askQuestion(user, "Perché me lo mostri?");
    await screen.findByText("Risposta.");

    const text = (container.textContent ?? "").toLowerCase();
    for (const forbidden of ["anthropic", "claude", "sonnet", "token", "gpt", "openai"]) {
      expect(text).not.toContain(forbidden);
    }
  });

  it("never renders a raw grounding_refs enum value anywhere", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: {
        status: "ANSWERED",
        answer: "Risposta.",
        grounding_refs: ["LATEST_FACTS", "RECOMMENDATION", "DECISION_STATUS"],
        limitations: [],
      },
    });
    const user = userEvent.setup();
    const { container } = renderPanel();

    await askQuestion(user, "Perché me lo mostri?");
    await screen.findByText("Risposta.");

    expect(container.textContent).not.toContain("LATEST_FACTS");
    expect(container.textContent).not.toContain("RECOMMENDATION");
    expect(container.textContent).not.toContain("DECISION_STATUS");
  });

  it("has no avatar, no chat bubble markup, no timestamp element", async () => {
    askNinfaMock.mockResolvedValue({
      ok: true,
      data: { status: "ANSWERED", answer: "Risposta.", grounding_refs: [], limitations: [] },
    });
    const user = userEvent.setup();
    const { container } = renderPanel();

    await askQuestion(user, "Perché me lo mostri?");
    await screen.findByText("Risposta.");

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelector("time")).toBeNull();
    expect(container.querySelector("[class*='avatar']")).toBeNull();
    expect(container.querySelector("[class*='bubble']")).toBeNull();
  });

  it("a new question replaces the previous answer - never accumulates a message list", async () => {
    askNinfaMock
      .mockResolvedValueOnce({
        ok: true,
        data: { status: "ANSWERED", answer: "Prima risposta.", grounding_refs: [], limitations: [] },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { status: "ANSWERED", answer: "Seconda risposta.", grounding_refs: [], limitations: [] },
      });
    const user = userEvent.setup();
    renderPanel();

    await askQuestion(user, "Prima domanda?");
    await screen.findByText("Prima risposta.");

    await user.clear(screen.getByLabelText("La tua domanda"));
    await askQuestion(user, "Seconda domanda?");

    expect(await screen.findByText("Seconda risposta.")).not.toBeNull();
    expect(screen.queryByText("Prima risposta.")).toBeNull();
    // Only one "Risposta di Mia" surface exists, never a growing list of past answers.
    expect(screen.getAllByText("Risposta di Mia").length).toBe(1);
  });

  it("a fresh mount (simulating a page refresh) starts idle - no persisted conversation to restore", () => {
    renderPanel();

    expect(screen.queryByText("Risposta di Mia")).toBeNull();
    expect((screen.getByLabelText("La tua domanda") as HTMLInputElement).value).toBe("");
    expect(askNinfaMock).not.toHaveBeenCalled();
  });
});
