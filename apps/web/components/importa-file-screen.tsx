"use client";

import type { DataSourceDomain, PropertyAccess } from "@ninfa/contracts";

import { strutturaRoute } from "@/lib/routes";
import { sourcesCopy } from "@/lib/sources/copy";
import { useRecentImports } from "@/lib/sources/use-recent-imports";

import { ImportaFileFlow } from "./importa-file-flow";
import { ImportaFileRecent } from "./importa-file-recent";
import { PropertyScreen } from "./property-screen";
import { StrutturaLinkButton } from "./struttura-parts";

const COPY = sourcesCopy.importPage;

function ImportaFileContent({
  property,
  review,
  onPropertyInvalid,
}: {
  property: PropertyAccess;
  review: DataSourceDomain | null;
  onPropertyInvalid: () => void;
}) {
  const recent = useRecentImports(property.id, onPropertyInvalid);

  return (
    <div className="importa-screen">
      <header className="struttura-screen__header">
        <div>
          <h1>{COPY.heading}</h1>
          <p className="struttura-screen__subtitle">{review === null ? COPY.subtitle : COPY.reviewSubtitle}</p>
        </div>
        {review !== null ? (
          <StrutturaLinkButton variant="soft" href={strutturaRoute(property.id)}>
            {COPY.backToSources}
          </StrutturaLinkButton>
        ) : null}
      </header>
      <ImportaFileFlow
        propertyId={property.id}
        timeZone={property.timezone}
        review={review}
        onImported={() => void recent.refresh()}
        onAccessLost={onPropertyInvalid}
      />
      <ImportaFileRecent recent={recent} timeZone={property.timezone} />
    </div>
  );
}

export interface ImportaFileScreenProps {
  /** The `?property=` query param, exactly as the URL carries it - `null` when absent. */
  requestedPropertyId: string | null;
  /** "Modifica associazioni" (Fonti dati): the kind of source whose columns are looked at again. */
  review?: DataSourceDomain | null;
  onSelectProperty: (propertyId: string) => void;
  onNavigateToLogin: () => void;
}

/** The full "/importa-file" screen: auth bootstrap gate, property resolution (0 / 1 / N properties), the sidebar
 * shell with "Importa file" active, and the page. Framework-free - `app/importa-file/page.tsx` wires it to the real
 * router; this is what gets tested. Switching property starts over: a file chosen for one never reaches another. */
export function ImportaFileScreen({
  requestedPropertyId,
  review = null,
  onSelectProperty,
  onNavigateToLogin,
}: ImportaFileScreenProps) {
  return (
    <PropertyScreen
      requestedPropertyId={requestedPropertyId}
      onSelectProperty={onSelectProperty}
      onNavigateToLogin={onNavigateToLogin}
      activeSection="importa-file"
    >
      {(selected, onPropertyInvalid) => (
        <ImportaFileContent
          key={`${selected.id}|${review ?? ""}`}
          property={selected}
          review={review}
          onPropertyInvalid={onPropertyInvalid}
        />
      )}
    </PropertyScreen>
  );
}
