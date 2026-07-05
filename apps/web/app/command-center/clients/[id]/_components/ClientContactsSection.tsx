"use client";

import { useState, useTransition } from "react";

import type {
  ClientContactDetail,
  ContactKind,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  createClientContactAction,
  deleteClientContactAction,
  updateClientContactAction,
} from "../actions";

const KINDS: ContactKind[] = [
  "phone_cell",
  "phone_home",
  "phone_work",
  "whatsapp",
  "signal",
  "telegram",
  "imessage",
  "instagram",
  "linkedin",
  "x",
  "facebook",
  "wechat",
  "other",
];

const KIND_LABELS: Record<ContactKind, string> = {
  phone_cell: "Cell",
  phone_home: "Home",
  phone_work: "Work",
  whatsapp: "WhatsApp",
  signal: "Signal",
  telegram: "Telegram",
  imessage: "iMessage",
  instagram: "Instagram",
  linkedin: "LinkedIn",
  x: "X",
  facebook: "Facebook",
  wechat: "WeChat",
  other: "Other",
};

const KIND_PLACEHOLDERS: Record<ContactKind, string> = {
  phone_cell: "+1 555 123 4567",
  phone_home: "+1 555 123 4567",
  phone_work: "+1 555 123 4567",
  whatsapp: "+1 555 123 4567",
  signal: "+1 555 123 4567",
  telegram: "@handle",
  imessage: "+1 555 123 4567 or email",
  instagram: "@handle",
  linkedin: "linkedin.com/in/handle",
  x: "@handle",
  facebook: "facebook.com/handle",
  wechat: "WeChat ID",
  other: "Value",
};

export function ClientContactsSection({
  clientId,
  contacts,
}: {
  clientId: string;
  contacts: ClientContactDetail[];
}) {
  return (
    <div className="flex flex-col gap-3">
      <AddContactForm clientId={clientId} />
      {contacts.length === 0 ? (
        <p className="font-sans text-sm italic text-paper/45">
          No contact methods yet.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-paper/10 border-y border-paper/10">
          {contacts.map((c) => (
            <li key={c.id}>
              <ContactRow clientId={clientId} contact={c} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AddContactForm({ clientId }: { clientId: string }) {
  const [kind, setKind] = useState<ContactKind>("phone_cell");
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const submit = () => {
    if (!value.trim()) return;
    setError(null);
    startTransition(async () => {
      const result = await createClientContactAction(clientId, {
        kind,
        value: value.trim(),
        label: label.trim(),
      });
      if ("error" in result) {
        setError(result.error);
      } else {
        setValue("");
        setLabel("");
      }
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex flex-col gap-2 rounded-sm border border-paper/15 bg-paper/9 p-3"
    >
      <div className="grid gap-2 sm:grid-cols-[8rem_1fr_8rem_auto]">
        <Select value={kind} onValueChange={(v) => setKind(v as ContactKind)}>
          <SelectTrigger className="h-9 border-paper/20 bg-transparent text-paper">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KINDS.map((k) => (
              <SelectItem key={k} value={k}>
                {KIND_LABELS[k]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          placeholder={KIND_PLACEHOLDERS[kind]}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="h-9 border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
        />
        <Input
          placeholder="Label (optional)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="h-9 border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
        />
        <Button
          type="submit"
          disabled={isPending || !value.trim()}
          size="sm"
          className="bg-paper text-ink hover:bg-paper/90"
        >
          {isPending ? "saving…" : "Add"}
        </Button>
      </div>
      {error ? (
        <p
          role="alert"
          className="font-sans text-xs font-medium text-destructive"
        >
          {error}
        </p>
      ) : null}
    </form>
  );
}

function ContactRow({
  clientId,
  contact,
}: {
  clientId: string;
  contact: ClientContactDetail;
}) {
  const [editing, setEditing] = useState(false);
  const [draftKind, setDraftKind] = useState<ContactKind>(contact.kind);
  const [draftValue, setDraftValue] = useState(contact.value);
  const [draftLabel, setDraftLabel] = useState(contact.label);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const onSave = () => {
    const value = draftValue.trim();
    if (!value) {
      setEditing(false);
      setDraftValue(contact.value);
      setDraftLabel(contact.label);
      setDraftKind(contact.kind);
      return;
    }
    setError(null);
    startTransition(async () => {
      const result = await updateClientContactAction(clientId, contact.id, {
        kind: draftKind,
        value,
        label: draftLabel.trim(),
      });
      if ("error" in result) {
        setError(result.error);
      } else {
        setEditing(false);
      }
    });
  };

  const onCancel = () => {
    setEditing(false);
    setDraftKind(contact.kind);
    setDraftValue(contact.value);
    setDraftLabel(contact.label);
    setError(null);
  };

  const onDelete = () => {
    if (
      !window.confirm(
        `Remove ${KIND_LABELS[contact.kind]} ${contact.value}?`,
      )
    )
      return;
    setError(null);
    startTransition(async () => {
      const result = await deleteClientContactAction(clientId, contact.id);
      if ("error" in result) setError(result.error);
    });
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-2 py-3">
        <div className="grid gap-2 sm:grid-cols-[8rem_1fr_8rem_auto]">
          <Select
            value={draftKind}
            onValueChange={(v) => setDraftKind(v as ContactKind)}
          >
            <SelectTrigger className="h-9 border-paper/20 bg-transparent text-paper">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {KINDS.map((k) => (
                <SelectItem key={k} value={k}>
                  {KIND_LABELS[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            value={draftValue}
            onChange={(e) => setDraftValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onSave();
              }
              if (e.key === "Escape") onCancel();
            }}
            autoFocus
            className="h-9 border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
          <Input
            placeholder="Label"
            value={draftLabel}
            onChange={(e) => setDraftLabel(e.target.value)}
            className="h-9 border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
          <div className="flex gap-1">
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
              disabled={isPending || !draftValue.trim()}
              className="bg-paper text-ink hover:bg-paper/90"
            >
              {isPending ? "saving…" : "Save"}
            </Button>
          </div>
        </div>
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

  return (
    <div className="group flex items-center gap-3 py-3">
      <span className="w-24 shrink-0 font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55">
        {KIND_LABELS[contact.kind]}
      </span>
      <span className="min-w-0 flex-1 truncate font-sans text-sm text-paper/90">
        {contact.value}
      </span>
      {contact.label ? (
        <span className="shrink-0 font-sans text-xs text-paper/55">
          {contact.label}
        </span>
      ) : null}
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
          onClick={onDelete}
          disabled={isPending}
          className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive"
        >
          Delete
        </button>
      </div>
      {error ? (
        <p
          role="alert"
          className="ml-2 font-sans text-xs font-medium text-destructive"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
