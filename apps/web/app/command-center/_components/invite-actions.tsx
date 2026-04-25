"use client";

import { useState, useTransition } from "react";

import type { InviteStatus } from "@ov-black/api-client";

import { cancelInviteAction, reissueInviteAction } from "../actions";

type Status =
  | { kind: "idle" }
  | { kind: "working"; op: "reissue" | "cancel" }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

interface InviteActionsProps {
  clientId: string;
  inviteStatus: InviteStatus;
}

/**
 * Resend / Cancel buttons for a single client row.
 *
 * Hidden when the client has already redeemed (``consumed``) or has no
 * invite history at all (``none``). The cancel button is hidden when the
 * latest invite is already cancelled — only resend remains in that state.
 *
 * Server actions are invoked through ``useTransition`` so the surrounding
 * row stays interactive while the request is in flight; the parent page
 * is revalidated by the action on success, which re-renders the badge.
 */
export function InviteActions({ clientId, inviteStatus }: InviteActionsProps) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  if (inviteStatus === "consumed" || inviteStatus === "none") {
    return null;
  }

  const showCancel = inviteStatus === "pending";

  const onReissue = () => {
    setStatus({ kind: "working", op: "reissue" });
    startTransition(async () => {
      const result = await reissueInviteAction(clientId);
      setStatus(
        result.ok
          ? { kind: "success", message: "New invite emailed." }
          : { kind: "error", message: result.error },
      );
    });
  };

  const onCancel = () => {
    setStatus({ kind: "working", op: "cancel" });
    startTransition(async () => {
      const result = await cancelInviteAction(clientId);
      setStatus(
        result.ok
          ? { kind: "success", message: "Invite cancelled." }
          : { kind: "error", message: result.error },
      );
    });
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onReissue}
          disabled={isPending}
          className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-paper disabled:opacity-50"
        >
          {status.kind === "working" && status.op === "reissue"
            ? "Resending…"
            : "Resend"}
        </button>
        {showCancel && (
          <>
            <span className="text-paper/20">·</span>
            <button
              type="button"
              onClick={onCancel}
              disabled={isPending}
              className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive disabled:opacity-50"
            >
              {status.kind === "working" && status.op === "cancel"
                ? "Cancelling…"
                : "Cancel"}
            </button>
          </>
        )}
      </div>
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
