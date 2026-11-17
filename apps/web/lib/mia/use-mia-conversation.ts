"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { MiaUiContext } from "@ninfa/contracts";

import { getMiaConversation, listMiaConversations, sendMiaMessage } from "@/lib/api/mia";
import { retainRecent, type Exchange } from "@/lib/ask-ninfa/conversation";

import { exchangesOfConversation, stateOfMiaResult } from "./state";

export type MiaConversationStatus = "idle" | "sending" | "error";

export interface UseMiaConversationOptions {
  propertyId: string;
  /** The property-local business date (`YYYY-MM-DD`) the person is looking at; sent verbatim. */
  asOfLocalDate: string;
  /** Called at the moment a message is sent: the validated hint about the screen (`ui_context`). */
  getUiContext?: () => MiaUiContext;
  /** Restore the person's latest conversation about this property on mount (default). */
  restore?: boolean;
}

export interface MiaConversationHandle {
  /** The newest few exchanges of the conversation, oldest first (what the screen draws). */
  exchanges: Exchange[];
  /** `sending` while a request runs; `error` when the newest exchange could not be completed. */
  status: MiaConversationStatus;
  /** The server's id of the conversation being continued; `null` before the first answer. */
  conversationId: string | null;
  /** The latest conversation is being fetched (only until the person sends or starts over). */
  restoring: boolean;
  /** Sends a NEW message. `false`: nothing was sent (empty text, or a request already running). */
  send: (text: string) => boolean;
  /** Sends the SAME message of an exchange again (an unavailable answer, by hand). */
  retry: (exchangeId: number) => boolean;
  /** "Nuova conversazione": forgets the current one here; the next message starts a new one on the
   * server. `false` while a request is running. */
  startNew: () => boolean;
}

/**
 * The conversation with Mia, shared by the Home and the panel of the other pages (Mia OpenAI
 * Intelligence V1). The conversation is the SERVER's: the browser keeps only what it draws and the id
 * to continue, and sends - per message - the text, the business date, that id and the hint about the
 * screen. Never a history, never a tool, never a property in the body.
 *
 * Behaviour that matters (each pinned by a test):
 * - exactly one request in flight, guarded SYNCHRONOUSLY (Enter + click, key repeat);
 * - the answer of a request that outlived its property, or its component, is dropped;
 * - a network/HTTP failure is shown as "unavailable", the same as the backend's own `UNAVAILABLE`;
 * - a conversation the server no longer has (404) is replaced by a new one, once, without telling
 *   the person anything went wrong;
 * - the latest conversation comes back after a refresh or a navigation, unless the person has already
 *   typed or started over.
 */
export function useMiaConversation({
  propertyId,
  asOfLocalDate,
  getUiContext,
  restore = true,
}: UseMiaConversationOptions): MiaConversationHandle {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [restoredFor, setRestoredFor] = useState<string | null>(null);
  const [scope, setScope] = useState(propertyId);

  const exchangesRef = useRef<Exchange[]>([]);
  const conversationIdRef = useRef<string | null>(null);
  const inFlightRef = useRef(false);
  const touchedRef = useRef(false);
  const nextIdRef = useRef(0);
  const scopeRef = useRef(propertyId);
  const mountedRef = useRef(true);
  const latestRef = useRef({ asOfLocalDate, getUiContext });

  // A different property is a different conversation: nothing carries over.
  if (scope !== propertyId) {
    setScope(propertyId);
    setExchanges([]);
    setConversationId(null);
  }

  useEffect(() => {
    exchangesRef.current = exchanges;
    latestRef.current = { asOfLocalDate, getUiContext };
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // The property changed (or the first mount): the old request, if any, can no longer block - nor land
  // on - this conversation; and the latest conversation of THIS property is fetched.
  useEffect(() => {
    scopeRef.current = propertyId;
    inFlightRef.current = false;
    touchedRef.current = false;
    conversationIdRef.current = null;
    if (!restore) return undefined;

    let cancelled = false;
    void (async () => {
      const listed = await listMiaConversations(propertyId);
      const latest = listed.ok ? listed.data.conversations[0] : undefined;
      const stored = latest === undefined ? null : await getMiaConversation(propertyId, latest.id);
      if (cancelled) return;
      if (stored !== null && stored.ok && !touchedRef.current) {
        const restored = exchangesOfConversation(stored.data, () => nextIdRef.current++);
        if (restored.length > 0) {
          conversationIdRef.current = stored.data.id;
          setConversationId(stored.data.id);
          setExchanges(restored);
        }
      }
      setRestoredFor(propertyId);
    })();
    return () => {
      cancelled = true;
    };
  }, [propertyId, restore]);

  const run = useCallback((text: string, retryOf?: number): boolean => {
    if (inFlightRef.current) return false; // a second request in the same tick never starts
    const trimmed = text.trim();
    if (trimmed.length === 0) return false;
    inFlightRef.current = true;
    touchedRef.current = true;
    const sentFor = scopeRef.current;

    let id: number;
    if (retryOf === undefined) {
      id = nextIdRef.current++;
      const fresh: Exchange = { id, question: trimmed, state: { kind: "loading" } };
      setExchanges((previous) => retainRecent([...previous, fresh]));
    } else {
      id = retryOf;
      setExchanges((previous) =>
        previous.map((exchange) =>
          exchange.id === id ? { ...exchange, state: { kind: "loading" } } : exchange,
        ),
      );
    }

    void (async () => {
      try {
        const { asOfLocalDate: asOf, getUiContext: readUiContext } = latestRef.current;
        const uiContext = readUiContext?.() ?? {};
        const message = (continuing: string | null) => ({
          message: trimmed,
          asOfLocalDate: asOf,
          conversationId: continuing,
          uiContext,
        });

        let result = await sendMiaMessage(sentFor, message(conversationIdRef.current));
        if (
          !result.ok &&
          result.status === 404 &&
          conversationIdRef.current !== null &&
          scopeRef.current === sentFor
        ) {
          // The server no longer has that conversation (it expired): start a new one, once.
          conversationIdRef.current = null;
          result = await sendMiaMessage(sentFor, message(null));
        }

        if (!mountedRef.current || scopeRef.current !== sentFor) return;
        const answeredIn = result.ok ? result.data.conversation_id : null;
        conversationIdRef.current = answeredIn ?? conversationIdRef.current;
        setConversationId(conversationIdRef.current);
        const state = stateOfMiaResult(result);
        setExchanges((previous) =>
          previous.map((exchange) => (exchange.id === id ? { ...exchange, state } : exchange)),
        );
      } finally {
        if (scopeRef.current === sentFor) inFlightRef.current = false;
      }
    })();
    return true;
  }, []);

  const send = useCallback((text: string) => run(text), [run]);

  const retry = useCallback(
    (exchangeId: number) => {
      const exchange = exchangesRef.current.find((item) => item.id === exchangeId);
      return exchange === undefined ? false : run(exchange.question, exchangeId);
    },
    [run],
  );

  const startNew = useCallback(() => {
    if (inFlightRef.current) return false;
    touchedRef.current = true;
    conversationIdRef.current = null;
    setConversationId(null);
    setExchanges([]);
    return true;
  }, []);

  const newest = exchanges[exchanges.length - 1];
  const status: MiaConversationStatus =
    newest?.state.kind === "loading"
      ? "sending"
      : newest?.state.kind === "unavailable" || newest?.state.kind === "error"
        ? "error"
        : "idle";

  return {
    exchanges,
    status,
    conversationId,
    restoring: restore && restoredFor !== propertyId,
    send,
    retry,
    startNew,
  };
}
