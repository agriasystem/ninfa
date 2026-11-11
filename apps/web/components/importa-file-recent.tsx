"use client";

import { useState } from "react";

import { sourcesCopy } from "@/lib/sources/copy";
import type { RecentImportsHandle } from "@/lib/sources/use-recent-imports";
import { formatSourceUpdate } from "@/lib/sources/view-model";

import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.importPage.recent;

export interface ImportaFileRecentProps {
  recent: RecentImportsHandle;
  timeZone: string;
}

/**
 * "Importazioni recenti": what really reached the backend and how it ended, as the backend recorded it. A failed
 * attempt says only that it failed. Nothing here is kept in the browser.
 */
export function ImportaFileRecent({ recent, timeZone }: ImportaFileRecentProps) {
  // "Oggi alle 09:31" is measured against ONE instant for the whole list.
  const [now] = useState(() => new Date());

  return (
    <section className="importa-recent" aria-labelledby="importa-recent-title">
      <h2 id="importa-recent-title" className="importa-recent__title">
        {COPY.title}
      </h2>

      {recent.status === "loading" ? (
        <p className="importa-recent__note" role="status">
          {COPY.loading}
        </p>
      ) : null}

      {recent.status === "error" ? (
        <div className="importa-recent__error" role="alert">
          <p className="importa-recent__note">{COPY.loadError}</p>
          <StrutturaButton variant="outline" onClick={() => void recent.refresh()}>
            {sourcesCopy.retry}
          </StrutturaButton>
        </div>
      ) : null}

      {recent.status === "ready" && recent.imports.length === 0 ? (
        <p className="importa-recent__note">{COPY.empty}</p>
      ) : null}

      {recent.status === "ready" && recent.imports.length > 0 ? (
        <table className="importa-recent__table">
          <thead>
            <tr>
              <th scope="col">{COPY.columns.file}</th>
              <th scope="col">{COPY.columns.kind}</th>
              <th scope="col">{COPY.columns.date}</th>
              <th scope="col">{COPY.columns.status}</th>
            </tr>
          </thead>
          <tbody>
            {recent.imports.map((item, index) => (
              <tr key={`${item.at}|${index}`}>
                <td className="importa-recent__file">{item.file_name ?? COPY.unnamed}</td>
                <td>{sourcesCopy.understanding.kindName[item.domain]}</td>
                <td>{formatSourceUpdate(item.at, { now, timeZone })}</td>
                <td>
                  <span className="importa-recent__status" data-status={item.status}>
                    {COPY.status[item.status]}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
