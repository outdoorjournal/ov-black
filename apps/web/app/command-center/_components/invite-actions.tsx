"use client";

import { useState, useTransition } from "react";

import type { AccessStatus } from "@ov-black/api-client";

import { resendWelcomeAction } from "../actions";

type Status =
  | { kind: "idle" }
  | { kind: "working" }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

interface InviteActionsProps {
  clientId: string;
  accessStatus: AccessStatus;
}

/**
 * Invite action for a single client row — issues the welcome sign-in link.
 *
 * Doubles as the ADV-1 invite-later affordance: for an ``uninvited`` client
 * (created silently) it sends the *first* invite ("Send invite"); for a
 * ``pending`` client (invited, not yet signed in) it re-sends ("Nudge"). Once
 * they're ``active`` there's nothing to send, so this renders nothing. Both
 * paths hit the same ``resend-welcome`` endpoint, which stamps the invite on
 * first send.
 *
 * The server action is invoked through ``useTransition`` so the surrounding
 * row stays interactive while the request is in flight; the parent page is
 * revalidated by the action on success.
 */
export function InviteActions({ clientId, accessStatus }: InviteActionsProps) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  if (accessStatus === "active") {
    return null;
  }

  const firstInvite = accessStatus === "uninvited";
  const idleLabel = firstInvite ? "Send invite" : "Nudge";
  const successCopy = firstInvite ? "Invite sent." : "Welcome link re-sent.";

  const onResend = () => {
    setStatus({ kind: "working" });
    startTransition(async () => {
      const result = await resendWelcomeAction(clientId);
      setStatus(
        result.ok
          ? { kind: "success", message: successCopy }
          : { kind: "error", message: result.error },
      );
    });
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        type="button"
        onClick={onResend}
        disabled={isPending}
        className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-paper disabled:opacity-50"
      >
        {status.kind === "working" ? "Sending…" : idleLabel}
      </button>
      {status.kind === "success" && (
        <p className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/60">
          {status.message}
        </p>
      )}
      {status.kind === "error" && (
        <p
          role="alert"
          className="font-sans text-[10px] uppercase tracking-[0.2em] text-destructive"
        >
          {status.message}
        </p>
      )}
    </div>
  );
}
