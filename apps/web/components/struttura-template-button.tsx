"use client";

import { useState } from "react";

import type { DataSourceDomain } from "@ninfa/contracts";

import { downloadTemplate } from "@/lib/api/data-sources";
import { sourcesCopy } from "@/lib/sources/copy";
import { saveBlob, TEMPLATE_FILENAME } from "@/lib/sources/save-file";

import { DownloadIcon } from "./icons";
import { StrutturaButton } from "./struttura-parts";

const COPY = sourcesCopy.importFlow;

/** "Scarica modello CSV": NINFA's own columns, for whoever has no file of their own yet. Costs have no template. */
export function StrutturaTemplateButton({
  propertyId,
  domain,
}: {
  propertyId: string;
  domain: Exclude<DataSourceDomain, "COSTS">;
}) {
  const [failed, setFailed] = useState(false);

  async function handleDownload() {
    const blob = await downloadTemplate(propertyId, domain);
    if (blob === null) {
      setFailed(true);
      return;
    }
    setFailed(false);
    saveBlob(blob, TEMPLATE_FILENAME[domain]);
  }

  return (
    <>
      <StrutturaButton variant="outline" Icon={DownloadIcon} onClick={() => void handleDownload()}>
        {COPY.template}
      </StrutturaButton>
      {failed ? (
        <p className="struttura-flow__error" role="alert">
          {COPY.templateFailed}
        </p>
      ) : null}
    </>
  );
}
