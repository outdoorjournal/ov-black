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
 * "Nudge" button for a single client row — re-sends the welcome sign-in link.
 *
 * Shown only while the client is ``pending`` (hasn't signed in yet). Once
 * they're ``active`` there's nothing to resend, so this renders nothing.
 *
 * The server action is invoked through ``useTransition`` so the surrounding
 * row stays interactive while the request is in flight; the parent page is
 * revalidated by the action on success.
 */
export function InviteActions({ clientId, accessStatus }: InviteActionsProps) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  if (accessStatus !== "pending") {
    return null;
  }

  const onResend = () => {
    setStatus({ kind: "working" });
    startTransition(async () => {
      const result = await resendWelcomeAction(clientId);
      setStatus(
        result.ok
          ? { kind: "success", message: "Welcome link re-sent." }
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
        {status.kind === "working" ? "Sending…" : "Nudge"}
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
