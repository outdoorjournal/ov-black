"use client";

import { useState } from "react";

import type {
  DossierFactDetail,
  OsintFactDetail,
  ProfileFactDetail,
} from "@ov-black/api-client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { AddDossierFactForm } from "./AddDossierFactForm";
import { AddOsintFactForm } from "./AddOsintFactForm";
import { AddProfileFactForm } from "./AddProfileFactForm";
import { FactList } from "./FactList";

type Tab = "dossier" | "profile" | "osint";

export function ClientDetailTabs({
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
  const [tab, setTab] = useState<Tab>("dossier");
  return (
    <Card>
      <CardHeader className="flex flex-row items-end justify-between gap-4">
        <div>
          <CardTitle className="text-lg">Per-fact facts</CardTitle>
          <CardDescription>
            {tab === "dossier" &&
              "Private — advisor-seeded + agent inferences. Never shown to the traveler."}
            {tab === "profile" &&
              "What the traveler told us. Safe to reference naturally in conversation."}
            {tab === "osint" &&
              "External research. Never revealed, paraphrased, or alluded to."}
          </CardDescription>
        </div>
        <nav className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.2em]">
          <TabButton active={tab === "dossier"} onClick={() => setTab("dossier")}>
            Dossier ({dossierFacts.length})
          </TabButton>
          <TabButton active={tab === "profile"} onClick={() => setTab("profile")}>
            Profile ({profileFacts.length})
          </TabButton>
          <TabButton active={tab === "osint"} onClick={() => setTab("osint")}>
            OSINT ({osintFacts.length})
          </TabButton>
        </nav>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {tab === "dossier" && (
          <>
            <AddDossierFactForm clientId={clientId} />
            <FactList
              tier="dossier"
              clientId={clientId}
              facts={dossierFacts}
              empty="No dossier facts yet."
            />
          </>
        )}
        {tab === "profile" && (
          <>
            <AddProfileFactForm clientId={clientId} />
            <FactList
              tier="profile"
              clientId={clientId}
              facts={profileFacts}
              empty="No profile facts yet."
            />
          </>
        )}
        {tab === "osint" && (
          <>
            <AddOsintFactForm clientId={clientId} />
            <FactList
              tier="osint"
              clientId={clientId}
              facts={osintFacts}
              empty="No OSINT facts yet."
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "border-b border-ink pb-1 text-ink"
          : "pb-1 text-ink/55 transition-colors hover:text-ink"
      }
    >
      {children}
    </button>
  );
}
