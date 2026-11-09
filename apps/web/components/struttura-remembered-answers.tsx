"use client";

import { useEffect, useId, useState, type ReactNode } from "react";

import type { RememberedAnswers, RememberedFile } from "@ninfa/contracts";

import {
  correctRememberedAnswer,
  forgetRememberedAnswer,
  getRememberedAnswers,
} from "@/lib/api/data-sources";
import { rememberedValueLabel, sourcesCopy } from "@/lib/sources/copy";

import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.manage.remembered;

type Load = { kind: "loading" } | { kind: "error" } | { kind: "loaded"; answers: RememberedAnswers };

type Working =
  | { kind: "idle" }
  | { kind: "correct"; id: string; value: string }
  | { kind: "forget"; id: string }
  | { kind: "busy" };

function FileLines({ file }: { file: RememberedFile }) {
  const said = [
    ...Object.entries(file.answers).map(([key, value]) => COPY.answerLabel(key, value)),
    ...(file.file_scope !== null ? [COPY.scopeLabel(file.file_scope)] : []),
    ...(file.column_decisions > 0 ? [COPY.columnsDecided(file.column_decisions)] : []),
  ];
  return (
    <span className="struttura-remembered__line">
      <span>{COPY.fileLine(file.columns)}</span>
      {said.map((line) => (
        <span key={line} className="struttura-remembered__said">
          {line}
        </span>
      ))}
    </span>
  );
}

export interface StrutturaRememberedAnswersProps {
  propertyId: string;
  sourceId: string;
}

/**
 * "Risposte ricordate" in "Gestisci": what NINFA learned from the person's answers and uses on the next file,
 * and the way to correct it without help. A word can be corrected, within the list the backend gives, or
 * forgotten; a kind of file can only be forgotten. Nothing here reads a file again: the note says so, and says
 * what to do if the data already imported are to change too. With nothing remembered the section is not there.
 */
export function StrutturaRememberedAnswers({ propertyId, sourceId }: StrutturaRememberedAnswersProps) {
  const titleId = useId();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [working, setWorking] = useState<Working>({ kind: "idle" });
  const [done, setDone] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    void getRememberedAnswers(propertyId, sourceId).then((result) => {
      if (current) setLoad(result.ok ? { kind: "loaded", answers: result.data } : { kind: "error" });
    });
    return () => {
      current = false;
    };
  }, [propertyId, sourceId]);

  if (load.kind === "loading") return null;
  if (load.kind === "error") {
    return (
      <p className="struttura-flow__error" role="alert">
        {COPY.loadError}
      </p>
    );
  }
  const { words, files } = load.answers;
  if (words.length === 0 && files.length === 0 && done === null) return null;

  async function apply(id: string, value: string | null) {
    setWorking({ kind: "busy" });
    setFailed(false);
    setDone(null);
    const result =
      value === null
        ? await forgetRememberedAnswer(propertyId, sourceId, id)
        : await correctRememberedAnswer(propertyId, sourceId, id, value);
    setWorking({ kind: "idle" });
    if (!result.ok) {
      setFailed(true);
      return;
    }
    setLoad({ kind: "loaded", answers: result.data });
    setDone(value === null ? COPY.forgotten : COPY.corrected);
  }

  const busy = working.kind === "busy";

  function actionsOf(id: string, field: string, choices: string[], value: string | null): ReactNode {
    if (working.kind === "forget" && working.id === id) {
      return (
        <div className="struttura-remembered__confirm">
          <p className="struttura-flow__note">{COPY.forgetBody}</p>
          <div className="struttura-flow__actions">
            <StrutturaButton variant="outline" onClick={() => setWorking({ kind: "idle" })}>
              {sourcesCopy.dialog.cancel}
            </StrutturaButton>
            <StrutturaButton variant="primary" onClick={() => void apply(id, null)}>
              {COPY.forgetConfirm}
            </StrutturaButton>
          </div>
        </div>
      );
    }
    if (working.kind === "correct" && working.id === id) {
      return (
        <div className="struttura-remembered__confirm">
          <label className="struttura-remembered__choice">
            {COPY.correctLabel}
            <select
              value={working.value}
              onChange={(event) => setWorking({ kind: "correct", id, value: event.target.value })}
            >
              {choices.map((choice) => (
                <option key={choice} value={choice}>
                  {choice === value
                    ? COPY.currentChoice(rememberedValueLabel(field, choice))
                    : rememberedValueLabel(field, choice)}
                </option>
              ))}
            </select>
          </label>
          <div className="struttura-flow__actions">
            <StrutturaButton variant="outline" onClick={() => setWorking({ kind: "idle" })}>
              {sourcesCopy.dialog.cancel}
            </StrutturaButton>
            <StrutturaButton variant="primary" onClick={() => void apply(id, working.value)}>
              {COPY.correctConfirm}
            </StrutturaButton>
          </div>
        </div>
      );
    }
    return (
      <div className="struttura-remembered__actions">
        {choices.length > 0 ? (
          <StrutturaButton
            variant="outline"
            disabled={busy}
            onClick={() => setWorking({ kind: "correct", id, value: value ?? choices[0] ?? "" })}
          >
            {COPY.correct}
          </StrutturaButton>
        ) : null}
        <StrutturaButton variant="outline" disabled={busy} onClick={() => setWorking({ kind: "forget", id })}>
          {COPY.forget}
        </StrutturaButton>
      </div>
    );
  }

  return (
    <section className="struttura-manage__configuration" aria-labelledby={titleId}>
      <h3 id={titleId} className="struttura-flow__subtitle">
        {COPY.title}
      </h3>
      <p className="struttura-flow__note">{COPY.intro}</p>
      {words.length + files.length > 0 ? (
        <ul className="struttura-remembered">
          {words.map((word) => (
            <li key={word.id} className="struttura-remembered__item">
              <span className="struttura-remembered__line">
                {COPY.wordLine(
                  COPY.fieldLabel(word.field),
                  word.label,
                  rememberedValueLabel(word.field, word.value),
                )}
              </span>
              {actionsOf(word.id, word.field, word.choices, word.value)}
            </li>
          ))}
          {files.map((file) => (
            <li key={file.id} className="struttura-remembered__item">
              <FileLines file={file} />
              {actionsOf(file.id, "", [], null)}
            </li>
          ))}
        </ul>
      ) : null}
      {failed ? (
        <p className="struttura-flow__error" role="alert">
          {sourcesCopy.problems.GENERIC}
        </p>
      ) : null}
      {done !== null ? (
        <p className="struttura-flow__note" role="status">
          {done} {COPY.notRetroactive}
        </p>
      ) : null}
    </section>
  );
}
