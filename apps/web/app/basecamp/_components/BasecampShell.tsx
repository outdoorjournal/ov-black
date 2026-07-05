"use client";

// Top-level client component for /basecamp. Decides which of the three
// rendered variants to mount based on what the server resolved:
//
//   - first_prompt        → SinglePromptCard (variants a / b — morphs in place)
//   - post_first_touch    → empty-itineraries hint + RightRailChat
//   - with_itineraries    → ItineraryGrid + RightRailChat
//
// All three share the same BasecampChrome backdrop. Variant (b) (active
// conversation after the morph) is owned entirely by SinglePromptCard's
// internal state — the server never resolves to "active conversation"
// because it's a transient client state, not a load shape.

import Link from "next/link";

import type {
  AgentTurnSummary,
  MyItinerarySummary,
  OnboardingOpenerResponse,
} from "@ov-black/api-client";

import { Eyebrow } from "@/components/ui/eyebrow";
import type { AppHeaderUser } from "@/lib/appHeader";

import { BasecampChrome } from "./BasecampChrome";
import { ItineraryGrid } from "./ItineraryGrid";
import { RightRailChat } from "./RightRailChat";
import { SinglePromptCard } from "./SinglePromptCard";

export type BasecampVariant = "first_prompt" | "post_first_touch" | "with_itineraries";

export type BasecampShellProps = {
  variant: BasecampVariant;
  // The resolved viewer, for the shared AppHeader masthead (PS7).
  user: AppHeaderUser;
  clientId: string;
  accessToken: string;
  apiBaseUrl: string;
  // Non-null on first_prompt; null on returning variants (the server skips
  // the bank lookup when it's not going to render the prompt UI).
  opener: OnboardingOpenerResponse | null;
  itineraries: MyItinerarySummary[];
  // Non-null when an onboarding session already exists for this client
  // (post_first_touch / with_itineraries). The right-rail chat reuses it
  // via createSessionEndpoint — open_or_reuse_session is idempotent.
  sessionId: string | null;
  priorTurns: AgentTurnSummary[];
  // The server's one "do we know enough about this traveler?" verdict
  // (evaluate_onboarding). When false on the post_first_touch variant we show
  // the "finish your introduction" reminder; RightRailChat also watches it to
  // fire the milestone card the moment it flips true (ONB-2A).
  onboardingComplete: boolean;
};

export function BasecampShell({
  variant,
  user,
  clientId,
  accessToken,
  apiBaseUrl,
  opener,
  itineraries,
  sessionId,
  priorTurns,
  onboardingComplete,
}: BasecampShellProps) {
  return (
    <BasecampChrome user={user}>
      {variant === "first_prompt" && opener !== null ? (
        <SinglePromptCard
          opener={opener}
          clientId={clientId}
          accessToken={accessToken}
          apiBaseUrl={apiBaseUrl}
        />
      ) : null}

      {variant === "post_first_touch" ? (
        <div className="grid min-h-[calc(100vh-5.5rem)] grid-cols-1 gap-6 px-6 pb-12 pt-6 sm:px-10 lg:grid-cols-[1fr_minmax(0,480px)] lg:gap-10">
          <div className="flex flex-col gap-6">
            <AccountLinks />
            {onboardingComplete ? <EmptyItinerariesHint /> : <OnboardingReminder />}
          </div>
          <RightRailChat
            clientId={clientId}
            accessToken={accessToken}
            apiBaseUrl={apiBaseUrl}
            initialTurns={priorTurns}
            existingSessionId={sessionId}
            onboardingComplete={onboardingComplete}
          />
        </div>
      ) : null}

      {variant === "with_itineraries" ? (
        <div className="grid min-h-[calc(100vh-5.5rem)] grid-cols-1 gap-6 px-6 pb-12 pt-6 sm:px-10 lg:grid-cols-[1fr_minmax(0,480px)] lg:gap-10">
          <div className="flex flex-col gap-6">
            <AccountLinks />
            <ItineraryGrid itineraries={itineraries} />
          </div>
          <RightRailChat
            clientId={clientId}
            accessToken={accessToken}
            apiBaseUrl={apiBaseUrl}
            initialTurns={priorTurns}
            existingSessionId={sessionId}
            onboardingComplete={onboardingComplete}
          />
        </div>
      ) : null}
    </BasecampChrome>
  );
}

function AccountLinks() {
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2">
      <Link
        href="/basecamp/party"
        className="font-sans text-[10px] uppercase tracking-eyebrow text-ink/55 transition-colors hover:text-ink"
      >
        Your travel party →
      </Link>
      <Link
        href="/basecamp/vault"
        className="font-sans text-[10px] uppercase tracking-eyebrow text-ink/55 transition-colors hover:text-ink"
      >
        Your vault →
      </Link>
      <Link
        href="/basecamp/invoices"
        className="font-sans text-[10px] uppercase tracking-eyebrow text-ink/55 transition-colors hover:text-ink"
      >
        Your invoices →
      </Link>
    </div>
  );
}

function EmptyItinerariesHint() {
  return (
    <div className="flex min-h-[40vh] flex-col items-start justify-center gap-6 lg:min-h-full">
      <Eyebrow rule>Your atelier</Eyebrow>
      <h2 className="max-w-xl font-serif text-4xl leading-[1.1] text-ink sm:text-5xl">
        Your itineraries will appear here.
      </h2>
      <p className="max-w-md text-base leading-relaxed text-ink/70">
        Reach the concierge any time — a thread to your right is always open.
      </p>
    </div>
  );
}

// Shown on the post_first_touch variant when the traveler skipped onboarding
// before telling us anything (no profile facts). A gentle nudge back into the
// always-open thread rather than a blocking gate — the concierge can't tailor
// anything until it knows a little about how they travel (ONB-2A).
function OnboardingReminder() {
  return (
    <div className="flex min-h-[40vh] flex-col items-start justify-center gap-6 lg:min-h-full">
      <Eyebrow rule>Your welcome, unfinished</Eyebrow>
      <h2 className="max-w-xl font-serif text-4xl leading-[1.1] text-ink sm:text-5xl">
        Tell us how you travel.
      </h2>
      <p className="max-w-md text-base leading-relaxed text-ink/70">
        You stepped away before your concierge could learn your tastes. Pick the
        thread back up whenever you like — a sentence or two is enough to begin.
      </p>
    </div>
  );
}
