"use client";

import { useState, useTransition } from "react";

import type {
  DossierFactDetail,
  OsintFactDetail,
  ProfileFactDetail,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";

import {
  redactDossierFactAction,
  redactOsintFactAction,
  redactProfileFactAction,
} from "../actions";

type Tier = "dossier" | "profile" | "osint";
type AnyFact = DossierFactDetail | ProfileFactDetail | OsintFactDetail;

export function FactList({
  tier,
  clientId,
  facts,
  empty,
}: {
  tier: Tier;
  clientId: string;
  facts: AnyFact[];
  empty: string;
}) {
  if (facts.length === 0) {
    return (
      <p className="font-sans text-sm italic text-ink/55">{empty}</p>
    );
  }
  return (
    <ul className="flex flex-col gap-3">
      {facts.map((fact) => (
        <li key={fact.id}>
          <FactRow tier={tier} clientId={clientId} fact={fact} />
        </li>
      ))}
    </ul>
  );
}

function FactRow({
  tier,
  clientId,
  fact,
}: {
  tier: Tier;
  clientId: string;
  fact: AnyFact;
}) {
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const onRedact = () => {
    const reason = window.prompt(
      "Why are you removing this fact? (kept for the audit trail)",
    );
    if (!reason || !reason.trim()) return;
    setError(null);
    startTransition(async () => {
      const action = redactActionFor(tier);
      const result = await action(clientId, fact.id, { reason: reason.trim() });
      if ("error" in result) setError(result.error);
    });
  };

  const observed = fact.observed_at ? formatDate(fact.observed_at) : "";
  const sourceRef = fact.source_ref as Record<string, unknown> | null | undefined;
  const url =
    sourceRef && typeof sourceRef["url"] === "string"
      ? (sourceRef["url"] as string)
      : null;

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-4">
      <div className="flex flex-wrap items-center gap-2 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/55">
        <Badge>{fact.kind}</Badge>
        <Badge>{fact.source_kind}</Badge>
        {observed ? <span>· {observed}</span> : null}
      </div>
      <p className="font-sans text-sm text-ink">{fact.text}</p>
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="font-sans text-xs text-ink/70 underline-offset-4 hover:underline"
        >
          {url}
        </a>
      ) : null}
      <div className="flex items-center justify-end gap-3">
        {error ? (
          <p
            role="alert"
            className="font-sans text-xs font-medium text-destructive"
          >
            {error}
          </p>
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRedact}
          disabled={isPending}
        >
          {isPending ? "removing…" : "Redact"}
        </Button>
      </div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-ink/5 px-2 py-0.5">{children}</span>
  );
}

function redactActionFor(tier: Tier) {
  if (tier === "dossier") return redactDossierFactAction;
  if (tier === "profile") return redactProfileFactAction;
  return redactOsintFactAction;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString();
}
