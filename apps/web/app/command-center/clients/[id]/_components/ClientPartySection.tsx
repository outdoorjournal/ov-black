"use client";

import { useState, useTransition } from "react";

import type { PartyMemberDetail } from "@ov-black/api-client";

import { PartyMemberForm } from "@/app/basecamp/party/_components/PartyMemberForm";
import { Button } from "@/components/ui/button";

import {
  archiveClientPartyMemberAction,
  createClientPartyMemberAction,
  updateClientPartyMemberAction,
} from "../actions";

// The advisor's view of a client's travel party — the "advisor sees
// completeness" surface. Reuses the same PartyMemberForm the traveler uses, so
// there's no parallel UI; the only difference is which actions it calls. Drives
// its list off the `members` prop; mutations revalidate the client detail path.

export function ClientPartySection({
  clientId,
  members,
}: {
  clientId: string;
  members: PartyMemberDetail[];
}) {
  const [adding, setAdding] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      {adding ? (
        <PartyMemberForm
          submitLabel="Add traveler"
          onSubmit={(payload) =>
            createClientPartyMemberAction(clientId, payload)
          }
          onCancel={() => setAdding(false)}
        />
      ) : (
        <Button
          type="button"
          variant="brand"
          size="sm"
          onClick={() => setAdding(true)}
          className="self-start"
        >
          Add traveler
        </Button>
      )}

      {members.length === 0 ? (
        <p className="font-sans text-sm italic text-paper/45">
          No travelers on file yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {members.map((m) => (
            <li key={m.id}>
              <MemberRow clientId={clientId} member={m} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MemberRow({
  clientId,
  member,
}: {
  clientId: string;
  member: PartyMemberDetail;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const onArchive = () => {
    if (!window.confirm(`Remove ${member.full_name} from this household?`)) {
      return;
    }
    setError(null);
    startTransition(async () => {
      const result = await archiveClientPartyMemberAction(clientId, member.id);
      if ("error" in result) setError(result.error);
    });
  };

  if (editing) {
    return (
      <PartyMemberForm
        member={member}
        submitLabel="Save changes"
        onSubmit={async (payload) => {
          const result = await updateClientPartyMemberAction(
            clientId,
            member.id,
            payload,
          );
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
    <div className="group flex items-start gap-4 rounded-sm border border-paper/10 bg-paper/4 px-4 py-3">
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
          <span className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/40">
            via {member.created_by_actor}
          </span>
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
