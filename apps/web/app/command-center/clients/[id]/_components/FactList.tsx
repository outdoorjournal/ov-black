"use client";

import { useState, useTransition } from "react";

import type {
  DossierFactDetail,
  OsintFactDetail,
  ProfileFactDetail,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import {
  redactDossierFactAction,
  redactOsintFactAction,
  redactProfileFactAction,
  updateDossierFactAction,
  updateOsintFactAction,
  updateProfileFactAction,
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
    return <p className="font-sans text-sm italic text-paper/45">{empty}</p>;
  }
  return (
    <ul className="flex flex-col divide-y divide-paper/10">
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
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fact.text);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const sourceRef = fact.source_ref as Record<string, unknown> | null | undefined;
  const url =
    sourceRef && typeof sourceRef["url"] === "string"
      ? (sourceRef["url"] as string)
      : null;

  const onSave = () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === fact.text) {
      setEditing(false);
      setDraft(fact.text);
      return;
    }
    setError(null);
    startTransition(async () => {
      const action = updateActionFor(tier);
      const result = await action(clientId, fact.id, { text: trimmed });
      if ("error" in result) {
        setError(result.error);
      } else {
        setEditing(false);
      }
    });
  };

  const onCancel = () => {
    setEditing(false);
    setDraft(fact.text);
    setError(null);
  };

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

  return (
    <div className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-2 font-sans text-[10px] uppercase tracking-[0.2em] text-paper/45">
        <Tag>{fact.kind}</Tag>
        <Tag tone="quiet">{fact.source_kind}</Tag>
        {fact.observed_at ? (
          <span>· {formatDate(fact.observed_at)}</span>
        ) : null}
      </div>

      {editing ? (
        <div className="flex flex-col gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSave();
              }
              if (e.key === "Escape") onCancel();
            }}
            autoFocus
            className="border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onCancel}
              disabled={isPending}
              className="text-paper/70 hover:bg-paper/10 hover:text-paper"
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={onSave}
              disabled={isPending || !draft.trim()}
              className="bg-paper text-ink hover:bg-paper/90"
            >
              {isPending ? "saving…" : "Save"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="break-words font-sans text-sm text-paper/90">
              {fact.text}
            </p>
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block break-all font-sans text-xs text-paper/60 underline-offset-4 hover:text-paper/90 hover:underline"
              >
                {url}
              </a>
            ) : null}
          </div>
          <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100 md:opacity-100">
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={isPending}
              className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-paper"
            >
              Edit
            </button>
            <span className="text-paper/20">·</span>
            <button
              type="button"
              onClick={onRedact}
              disabled={isPending}
              className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive"
            >
              Redact
            </button>
          </div>
        </div>
      )}

      {error ? (
        <p
          role="alert"
          className="font-sans text-xs font-medium text-destructive"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}

function Tag({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "quiet";
}) {
  const cls =
    tone === "quiet"
      ? "border-paper/15 text-paper/45"
      : "border-paper/25 text-paper/70";
  return (
    <span
      className={`rounded-full border ${cls} px-2 py-0.5 font-sans text-[9px] uppercase tracking-[0.2em]`}
    >
      {children}
    </span>
  );
}

function updateActionFor(tier: Tier) {
  if (tier === "dossier") return updateDossierFactAction;
  if (tier === "profile") return updateProfileFactAction;
  return updateOsintFactAction;
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
