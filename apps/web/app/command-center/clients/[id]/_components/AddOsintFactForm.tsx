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

import { createOsintFactAction } from "../actions";

const KINDS = [
  "linkedin",
  "facebook",
  "instagram",
  "press",
  "company",
  "public_record",
  "other",
] as const;

export function AddOsintFactForm({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<(typeof KINDS)[number]>("linkedin");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const submit = () => {
    if (!text.trim()) return;
    setError(null);
    startTransition(async () => {
      const sourceRef: Record<string, unknown> = {};
      if (url.trim()) sourceRef["url"] = url.trim();
      const result = await createOsintFactAction(clientId, {
        kind,
        text: text.trim(),
        source_kind: "advisor",
        source_ref: sourceRef,
        observed_at: null,
      });
      if ("error" in result) {
        setError(result.error);
      } else {
        setText("");
        setUrl("");
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
      <div className="grid gap-2 sm:grid-cols-[8rem_1fr_1fr]">
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
        <Input
          placeholder="What did you find?"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-9 border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
        />
        <Input
          placeholder="Source URL (optional)"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
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
