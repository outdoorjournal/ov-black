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
import { Textarea } from "@/components/ui/textarea";

import { createDossierFactAction } from "../actions";

const KINDS = [
  "passion",
  "motivation",
  "travel_history",
  "trigger",
  "constraint",
  "deal_breaker",
  "dream_signal",
  "party",
  "preference",
  "other",
] as const;

const SOURCE_KINDS = ["advisor", "agent_inferred"] as const;

export function AddDossierFactForm({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<(typeof KINDS)[number]>("passion");
  const [sourceKind, setSourceKind] = useState<(typeof SOURCE_KINDS)[number]>("advisor");
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
      className="flex flex-col gap-3 rounded-md border border-border p-4"
    >
      <div className="grid gap-3 sm:grid-cols-[10rem_10rem_1fr]">
        <Select value={kind} onValueChange={(v) => setKind(v as typeof kind)}>
          <SelectTrigger>
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
          <SelectTrigger>
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
          placeholder="What is the fact?"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </div>
      <div className="flex items-center justify-end gap-3">
        {error ? (
          <p
            role="alert"
            className="font-sans text-xs font-medium text-destructive"
          >
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={isPending || !text.trim()} size="sm">
          {isPending ? "saving…" : "Add fact"}
        </Button>
      </div>
    </form>
  );
}
