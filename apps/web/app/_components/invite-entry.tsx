"use client";

import { useMemo, useState, type FormEvent } from "react";
import {
  createApiClient,
  redeemInvite,
  type RedeemInviteDetail,
} from "@ov-black/api-client";

type Status =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "sent" }
  | { kind: "error"; message: string };

// Map of API detail codes (see apps/api/app/routers/auth.py) to human copy
// that keeps the code-enumeration guarantee from D015 intact: unknown-code
// and wrong-email must look identical to the user.
function messageForDetail(status: number, detail: RedeemInviteDetail): string {
  if (status === 404 && detail === "invite_not_redeemable") {
    return "That invite code isn't redeemable with this email.";
  }
  if (status === 409 && detail === "invite_already_consumed") {
    return "This invite has already been used.";
  }
  if (status === 502 || detail === "auth_upstream_unavailable") {
    return "Our concierge is stepping away for a moment. Please try again.";
  }
  if (detail === "network_error") {
    return "Could not reach the server. Check your connection.";
  }
  return "Something went wrong. Please try again.";
}

export function InviteEntry() {
  const [code, setCode] = useState("");
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const apiBaseUrl = process.env["NEXT_PUBLIC_API_BASE_URL"] ?? "";
  const client = useMemo(
    () => createApiClient({ baseUrl: apiBaseUrl }),
    [apiBaseUrl],
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus({ kind: "submitting" });

    const result = await redeemInvite(client, {
      code: code.trim(),
      email: email.trim(),
    });

    if (result.ok) {
      setStatus({ kind: "sent" });
      return;
    }

    setStatus({
      kind: "error",
      message: messageForDetail(result.status, result.detail),
    });
  }

  if (status.kind === "sent") {
    return (
      <div
        className="rounded border border-ink/10 bg-white/60 p-6"
        role="status"
        aria-live="polite"
      >
        <h2 className="font-serif text-2xl text-ink">Check your inbox.</h2>
        <p className="mt-2 text-sm text-ink/70">
          A sign-in link is on its way to {email}.
        </p>
      </div>
    );
  }

  const submitting = status.kind === "submitting";

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <div>
        <label
          htmlFor="invite-code"
          className="block text-xs uppercase tracking-[0.2em] text-ink/60"
        >
          Invite code
        </label>
        <input
          id="invite-code"
          name="code"
          type="text"
          autoComplete="one-time-code"
          required
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="mt-1 block w-full rounded border border-ink/20 bg-white px-3 py-2 font-mono text-sm text-ink focus:border-ink focus:outline-none"
        />
      </div>

      <div>
        <label
          htmlFor="invite-email"
          className="block text-xs uppercase tracking-[0.2em] text-ink/60"
        >
          Email
        </label>
        <input
          id="invite-email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 block w-full rounded border border-ink/20 bg-white px-3 py-2 text-sm text-ink focus:border-ink focus:outline-none"
        />
      </div>

      {status.kind === "error" ? (
        <p className="text-sm text-red-700" role="alert">
          {status.message}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={submitting || code.trim() === "" || email.trim() === ""}
        className="w-full rounded bg-ink px-4 py-2 text-sm uppercase tracking-[0.2em] text-paper transition hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Sending…" : "Request sign-in link"}
      </button>
    </form>
  );
}
