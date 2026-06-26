"use client";

import Link from "next/link";
import { useState, useTransition } from "react";

import type { PartyMemberCreate, PartyMemberDetail } from "@ov-black/api-client";

import { Button } from "@/components/ui/button";

import {
  archiveMyPartyMemberAction,
  createMyPartyMemberAction,
  updateMyPartyMemberAction,
} from "../actions";
import { PartyMemberForm } from "./PartyMemberForm";

// Traveler self-service roster. Drives its list straight off the `members`
// prop — every mutation revalidates `/basecamp/party`, so the RSC re-reads and
// hands fresh props back. Local state only governs the add/edit UI. Mirrors
// the advisor ClientContactsSection editing model.

export function PartyManager({ members }: { members: PartyMemberDetail[] }) {
  const [adding, setAdding] = useState(false);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 pb-16 pt-2 sm:px-10">
      <header className="flex flex-col gap-3 border-b border-paper/10 pb-6">
        <Link
          href="/basecamp"
          className="font-sans text-[10px] uppercase tracking-[0.4em] text-paper/55 transition-colors hover:text-paper"
        >
          ← Basecamp
        </Link>
        <h1 className="font-serif text-4xl tracking-tight text-paper sm:text-5xl">
          Your travel party
        </h1>
        <p className="max-w-xl font-sans text-sm leading-relaxed text-paper/70">
          The people who travel with you, remembered across every trip. Add a
          traveler once — passport details, dietary needs, loyalty numbers — and
          your concierge carries them forward.
        </p>
      </header>

      {members.length === 0 && !adding ? (
        <p className="font-sans text-sm italic text-paper/45">
          No travelers yet. Add the first to begin.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {members.map((m) => (
            <li key={m.id}>
              <MemberRow member={m} />
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <PartyMemberForm
          submitLabel="Add traveler"
          onSubmit={(payload: PartyMemberCreate) =>
            createMyPartyMemberAction(payload)
          }
          onCancel={() => setAdding(false)}
        />
      ) : (
        <Button
          type="button"
          onClick={() => setAdding(true)}
          className="self-start bg-paper text-ink hover:bg-paper/90"
        >
          Add a traveler
        </Button>
      )}
    </div>
  );
}

function MemberRow({ member }: { member: PartyMemberDetail }) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const onArchive = () => {
    if (!window.confirm(`Remove ${member.full_name} from your travel party?`)) {
      return;
    }
    setError(null);
    startTransition(async () => {
      const result = await archiveMyPartyMemberAction(member.id);
      if ("error" in result) setError(result.error);
    });
  };

  if (editing) {
    return (
      <PartyMemberForm
        member={member}
        submitLabel="Save changes"
        onSubmit={async (payload) => {
          const result = await updateMyPartyMemberAction(member.id, payload);
          if (!("error" in result)) setEditing(false);
          return result;
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const summary = [member.nationality, member.dietary, member.mobility]
    .filter((s): s is string => Boolean(s && s.trim()))
    .join(" · ");

  return (
    <div className="group flex items-start gap-4 rounded-sm border border-paper/10 bg-paper/[0.04] px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-serif text-lg tracking-tight text-paper">
            {member.full_name}
          </span>
          {member.is_primary ? (
            <span className="rounded-full border border-paper/30 px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em] text-paper/70">
              Primary
            </span>
          ) : null}
          {member.relationship_to_primary ? (
            <span className="font-sans text-xs text-paper/55">
              {member.relationship_to_primary}
            </span>
          ) : null}
        </div>
        <p className="mt-1 font-sans text-xs text-paper/55">
          {member.date_of_birth ? `Born ${member.date_of_birth}` : "DOB not set"}
          {summary ? ` · ${summary}` : ""}
        </p>
        {error ? (
          <p role="alert" className="mt-1 font-sans text-xs text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 gap-2 opacity-0 transition-opacity group-hover:opacity-100 md:opacity-100">
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
          onClick={onArchive}
          disabled={isPending}
          className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive"
        >
          Remove
        </button>
      </div>
    </div>
  );
}
