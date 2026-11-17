import { screen } from "@testing-library/react";
import type userEvent from "@testing-library/user-event";

import type { MiaAnswerResponse } from "@ninfa/contracts";

/** A normal answer of the Mia endpoint, for the tests of screens that only care what a message carries. */
export const MIA_ANSWER: { ok: true; data: MiaAnswerResponse } = {
  ok: true,
  data: {
    status: "ANSWERED",
    answer: "Ecco.",
    limitations: [],
    grounding_refs: [],
    conversation_id: "conv-1",
  },
};

/** What `@/lib/api/mia` is replaced with in a screen test: no network, no stored conversation. */
export const MIA_NO_CONVERSATIONS = { ok: true as const, data: { conversations: [] } };

/** The person opens Mia from the shell's launcher and sends a message: the whole path a screen's
 * published context takes to the request body. */
export async function askMiaFromLauncher(
  user: ReturnType<typeof userEvent.setup>,
  message: string,
): Promise<void> {
  await user.click(screen.getByRole("button", { name: "Apri la conversazione con Mia" }));
  await user.type(screen.getByRole("textbox", { name: "La tua domanda per Mia" }), `${message}{Enter}`);
}
