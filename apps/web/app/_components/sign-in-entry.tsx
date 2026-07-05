"use client";

import { useMemo, useState, type FormEvent } from "react";
import {
  createApiClient,
  requestLogin,
  type RequestLoginDetail,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { publicEnv } from "@/lib/env";

type Status =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "sent" }
  | { kind: "error"; message: string };

// The API collapses "link sent" and "no account" into the same 204, so
// the success state here means "we asked Supabase to try" — the user is
// told to check their inbox either way. Only the distinct failure shapes
// (upstream down, validation, network) get user-facing copy.
function messageForDetail(detail: RequestLoginDetail): string {
  if (detail === "auth_upstream_unavailable") {
    return "Our concierge is stepping away for a moment. Please try again.";
  }
  if (detail === "validation_error") {
    return "Please enter a valid email address.";
  }
  if (detail === "network_error") {
    return "Could not reach the server. Check your connection.";
  }
  return "Something went wrong. Please try again.";
}

export function SignInEntry() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const { apiBaseUrl } = publicEnv();
  const client = useMemo(
    () => createApiClient({ baseUrl: apiBaseUrl }),
    [apiBaseUrl],
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus({ kind: "submitting" });

    const result = await requestLogin(client, { email: email.trim() });

    if (result.ok) {
      setStatus({ kind: "sent" });
      return;
    }

    setStatus({
      kind: "error",
      message: messageForDetail(result.detail),
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
          If {email} matches an account, a sign-in link is on its way.
        </p>
      </div>
    );
  }

  const submitting = status.kind === "submitting";

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <div>
        <label
          htmlFor="sign-in-email"
          className="block text-xs uppercase tracking-[0.2em] text-ink/60"
        >
          Email
        </label>
        <input
          id="sign-in-email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 block w-full rounded border border-ink/20 bg-white px-3 py-2.5 text-sm text-ink transition focus:border-brand focus:outline-hidden focus:ring-2 focus:ring-brand/30"
        />
      </div>

      {status.kind === "error" ? (
        <p className="text-sm text-red-700" role="alert">
          {status.message}
        </p>
      ) : null}

      <Button
        type="submit"
        variant="brand"
        disabled={submitting || email.trim() === ""}
        className="w-full uppercase tracking-label"
      >
        {submitting ? "Sending…" : "Send sign-in link"}
      </Button>
    </form>
  );
}
