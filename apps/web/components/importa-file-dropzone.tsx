"use client";

import { useRef, useState, type ChangeEvent, type DragEvent } from "react";

import type { ImportLimitsResponse } from "@ninfa/contracts";

import { sourcesCopy } from "@/lib/sources/copy";
import { fileAcceptOf, fileSizeText } from "@/lib/sources/use-import-limits";

import { UploadIcon } from "./icons";

const COPY = sourcesCopy.importPage.drop;

export interface ImportaFileDropzoneProps {
  /** Why the last file was not taken, already in plain words. */
  problem: string | null;
  /** What a file may be, as the backend said (`null`: it has not said yet). */
  limits: ImportLimitsResponse | null;
  onFiles: (files: readonly File[]) => void;
}

/**
 * The file comes in here: dragged onto the zone or picked from the computer. The whole zone is the `<label>` of a
 * real file input, so a click opens the picker and the keyboard reaches it like any other control - no library and
 * no script for what the browser already does. It looks at nothing but the list of files: what they are is for the
 * flow to judge.
 */
export function ImportaFileDropzone({ problem, limits, onFiles }: ImportaFileDropzoneProps) {
  const [dragging, setDragging] = useState(false);
  // Crossing a child of the zone fires leave + enter on the zone: only the last leave is the real one.
  const depth = useRef(0);

  function handleDragEnter(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    depth.current += 1;
    setDragging(true);
  }

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault(); // without this the browser does not allow a drop here
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDragLeave() {
    depth.current = Math.max(0, depth.current - 1);
    if (depth.current === 0) setDragging(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    depth.current = 0;
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onFiles(files); // (text or a link dragged by mistake carries no file)
  }

  function handlePick(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = ""; // the same file can be chosen again after a correction
    if (files.length > 0) onFiles(files);
  }

  return (
    <>
      <label
        className="importa-drop"
        data-dragging={dragging ? "true" : "false"}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <span className="importa-drop__icon" aria-hidden="true">
          <UploadIcon />
        </span>
        <span className="importa-drop__title">{COPY.title}</span>
        <span className="importa-drop__or">{COPY.or}</span>
        <span className="struttura-button struttura-button--primary importa-drop__pick">{COPY.pick}</span>
        <span className="importa-drop__formats">
          {COPY.formats(limits === null ? null : fileSizeText(limits.max_file_bytes))}
        </span>
        <input
          type="file"
          className="visually-hidden"
          accept={fileAcceptOf(limits)}
          aria-label={COPY.inputLabel}
          onChange={handlePick}
        />
      </label>
      {problem !== null ? (
        <p className="importa-flow__rejected struttura-flow__error" role="alert">
          {problem}
        </p>
      ) : null}
    </>
  );
}
