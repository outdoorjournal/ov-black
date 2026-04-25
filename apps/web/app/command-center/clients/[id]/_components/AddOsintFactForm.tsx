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
      className="flex flex-col gap-3 rounded-md border border-border p-4"
    >
      <div className="grid gap-3 sm:grid-cols-[10rem_1fr_1fr]">
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
        <Input
          placeholder="What did you find?"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Input
          placeholder="Source URL (optional)"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
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
          {isPending ? "saving…" : "Add OSINT fact"}
        </Button>
      </div>
    </form>
  );
}
