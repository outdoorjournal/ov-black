"use client";

import { useState, useTransition } from "react";

import type {
  DocumentDetail,
  DocumentUpdate,
  PartyMemberDetail,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// Compact metadata editor for an existing document — label, the optional
// party-member link, expiry, and notes. No file re-upload (that's a fresh
// document); this only patches the row. Shared by the traveler + advisor
// managers, so it takes an `onSave(patch)` the caller wires to the right action.

const inputCls =
  "h-9 w-full rounded-sm border border-paper/20 bg-transparent px-2 font-sans text-sm text-paper placeholder:text-paper/40 focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-paper/30";
const labelCls =
  "font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55";

export function DocumentMetaForm({
  document,
  members,
  onSave,
  onCancel,
}: {
  document: DocumentDetail;
  members: PartyMemberDetail[];
  onSave: (patch: DocumentUpdate) => Promise<{ ok: true } | { error: string }>;
  onCancel: () => void;
}) {
  const [label, setLabel] = useState(document.label ?? "");
  const [memberId, setMemberId] = useState(document.party_member_id ?? "");
  const [expiresAt, setExpiresAt] = useState(document.expires_at ?? "");
  const [notes, setNotes] = useState(document.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const save = () => {
    setError(null);
    startTransition(async () => {
      const result = await onSave({
        label: label.trim() || null,
        party_member_id: memberId ? memberId : null,
        expires_at: expiresAt.trim() || null,
        notes: notes.trim() || null,
      });
      if ("error" in result) setError(result.error);
      else onCancel();
    });
  };

  return (
    <div className="flex flex-col gap-3 rounded-sm border border-paper/15 bg-paper/6 p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Label</span>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Belongs to</span>
          <select
            value={memberId}
            onChange={(e) => setMemberId(e.target.value)}
            className={inputCls}
          >
            <option value="" className="text-ink">
              — whole household —
            </option>
            {members.map((m) => (
              <option key={m.id} value={m.id} className="text-ink">
                {m.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Expires</span>
          <input
            type="date"
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
            className={inputCls}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1">
        <span className={labelCls}>Notes</span>
        <Textarea
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
        />
      </label>
      {error ? (
        <p role="alert" className="font-sans text-xs font-medium text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex items-center justify-end gap-3">
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
          onClick={save}
          disabled={isPending}
          className="bg-paper text-ink hover:bg-paper/90"
        >
          {isPending ? "saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}
