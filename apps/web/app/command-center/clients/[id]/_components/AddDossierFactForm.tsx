"use client";

import { useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { createDossierFactAction } from "../actions";

const KINDS = [
  "passion",
  "motivation",
  "travel_history",
  "trigger",
  "constraint",
  "deal_breaker",
  "dream_signal",
  "preference",
  "other",
] as const;

const SOURCE_KINDS = ["advisor", "agent_inferred"] as const;

export function AddDossierFactForm({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<(typeof KINDS)[number]>("passion");
  const [sourceKind, setSourceKind] =
    useState<(typeof SOURCE_KINDS)[number]>("advisor");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const submit = () => {
    if (!text.trim()) return;
    setError(null);
    startTransition(async () => {
      const result = await createDossierFactAction(clientId, {
        kind,
        text: text.trim(),
        source_kind: sourceKind,
        source_ref: {},
        observed_at: null,
      });
      if ("error" in result) {
        setError(result.error);
      } else {
        setText("");
      }
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex flex-col gap-2 rounded-sm border border-paper/15 bg-paper/[0.09] p-3"
    >
      <div className="grid gap-2 sm:grid-cols-[8rem_8rem_1fr]">
        <Select value={kind} onValueChange={(v) => setKind(v as typeof kind)}>
          <SelectTrigger className="h-9 border-paper/20 bg-transparent text-paper">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KINDS.map((k) => (
              <SelectItem key={k} value={k}>
                {k}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={sourceKind}
          onValueChange={(v) => setSourceKind(v as typeof sourceKind)}
        >
          <SelectTrigger className="h-9 border-paper/20 bg-transparent text-paper">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SOURCE_KINDS.map((k) => (
              <SelectItem key={k} value={k}>
                {k}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          placeholder="A private fact…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-9 border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
        />
      </div>
      <div className="flex items-center justify-between gap-3">
        {error ? (
          <p
            role="alert"
            className="font-sans text-xs font-medium text-destructive"
          >
            {error}
          </p>
        ) : (
          <span />
        )}
        <Button
          type="submit"
          disabled={isPending || !text.trim()}
          size="sm"
          className="bg-paper text-ink hover:bg-paper/90"
        >
          {isPending ? "saving…" : "Add"}
        </Button>
      </div>
    </form>
  );
}
