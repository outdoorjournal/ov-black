"use client";

import type {
  DossierFactDetail,
  OsintFactDetail,
  ProfileFactDetail,
} from "@ov-black/api-client";

import { AddDossierFactForm } from "./AddDossierFactForm";
import { AddOsintFactForm } from "./AddOsintFactForm";
import { AddProfileFactForm } from "./AddProfileFactForm";
import { FactList } from "./FactList";

/**
 * Three-tier fact workspace. Renders Dossier · Profile · OSINT side-by-side
 * on desktop and stacked on mobile, with the disclosure rule baked into each
 * column's header so the advisor can never confuse what the agent will say
 * back to the traveler.
 */
export function ClientFactColumns({
  clientId,
  dossierFacts,
  profileFacts,
  osintFacts,
}: {
  clientId: string;
  dossierFacts: DossierFactDetail[];
  profileFacts: ProfileFactDetail[];
  osintFacts: OsintFactDetail[];
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <Column
        title="Dossier"
        count={dossierFacts.length}
        rule="Private — never shown to traveler."
        ruleTone="warn"
      >
        <AddDossierFactForm clientId={clientId} />
        <FactList
          tier="dossier"
          clientId={clientId}
          facts={dossierFacts}
          empty="No dossier facts yet."
        />
      </Column>
      <Column
        title="Profile"
        count={profileFacts.length}
        rule="What the traveler told us — safe to reference."
        ruleTone="ok"
      >
        <AddProfileFactForm clientId={clientId} />
        <FactList
          tier="profile"
          clientId={clientId}
          facts={profileFacts}
          empty="No profile facts yet."
        />
      </Column>
      <Column
        title="OSINT"
        count={osintFacts.length}
        rule="External research — never reveal or allude to."
        ruleTone="warn"
      >
        <AddOsintFactForm clientId={clientId} />
        <FactList
          tier="osint"
          clientId={clientId}
          facts={osintFacts}
          empty="No OSINT facts yet."
        />
      </Column>
    </div>
  );
}

function Column({
  title,
  count,
  rule,
  ruleTone,
  children,
}: {
  title: string;
  count: number;
  rule: string;
  ruleTone: "ok" | "warn";
  children: React.ReactNode;
}) {
  const tone =
    ruleTone === "warn" ? "text-amber-200/80" : "text-emerald-200/80";
  return (
    <section className="flex flex-col gap-3 group" aria-label={title}>
      <header className="flex items-baseline justify-between gap-3 border-b border-paper/10 pb-2">
        <div className="flex items-baseline gap-3">
          <h3 className="font-serif text-xl tracking-tight text-paper">
            {title}
          </h3>
          <span className="font-sans text-[10px] uppercase tracking-[0.3em] text-paper/45">
            {count}
          </span>
        </div>
      </header>
      <p className={`font-sans text-[10px] uppercase tracking-[0.25em] ${tone}`}>
        {rule}
      </p>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}
