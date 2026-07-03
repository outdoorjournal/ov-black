# Onboarding — QA Scenarios

Area code: **ONB**. See [README.md](./README.md) for the scenario format, status
legend, and how these map to e2e tests.

New-user lifecycle: an advisor invites a traveler, the traveler signs in from the
emailed link, completes (or skips) the AI-concierge onboarding chat that builds
their Dossier, and later revises their preferences.

> **"P#" below = the CLI/pytest pillar suite** (`apps/cli/tests/e2e/test_pillarN_*_e2e.py`),
> which already exercises much of this lifecycle at the API seam. These scenarios
> cite that coverage rather than duplicate it; net-new tests should target the
> **gaps** called out in each **Notes** block (mostly advisor/traveler *UI* states
> and the email/SMTP boundary). See the README's "pillar suite" note.

## Coverage at a glance

| Scenario | Title | Status | Automated by (layer) |
| --- | --- | --- | --- |
| [ONB-1](#onb-1--advisor-invites-a-new-user) | Advisor invites a new user | 🟡 Partial | P1 invite (API) + traveler landing (web); real email delivery not automatable |
| [ONB-1A](#onb-1a--invitee-already-has-an-account) | Invitee already has an account | 🚧 Planned | — (gap: no advisor-facing "already registered" test) |
| [ONB-1B](#onb-1b--invitee-never-receives-the-email) | Invitee never receives the email | 🟡 Partial | P1 resend nudge (API); out-of-band code/link recovery not automatable |
| [ONB-2](#onb-2--new-user-completes-the-onboarding-flow) | New user completes the onboarding flow | 🟡 Partial | P2 dream/profile (API) + new-user landing (web); positive completion Bedrock-gated |
| [ONB-2A](#onb-2a--user-skips-the-onboarding-flow) | User skips the onboarding flow (nudge) | ✅ Automated | Nudge built; skip→reminder (web) + `has_profile_facts` signal (API) |
| [ONB-3](#onb-3--user-adjusts-preferences-after-onboarding) | User adjusts preferences after onboarding | 🟡 Partial | P4 self-service party/vault (API); general-preferences UI thin |

---

## ONB-1 · Advisor invites a new user

- **Status:** 🟡 Partial
- **Personas:** Advisor → Traveler
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** Advisor is signed in. The target email has no existing account.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar1_invite_e2e.py::test_advisor_adds_client_and_welcome_is_sent` — client + Dossier created atomically, welcome sent, `access_status == "pending"`, `accepted_at is None`.
  - `apps/cli/tests/e2e/test_pillar1_invite_e2e.py::test_login_unknown_email_does_not_enumerate` — the security guarantee (unknown email → same 204).
  - `apps/cli/tests/e2e/test_pillar1_invite_e2e.py::test_linked_traveler_lands_in_their_chat` — post-sign-in landing: `GET /me/client` resolves, chat session opens.
  - `apps/web/e2e/traveler.setup.ts` + `apps/web/e2e/traveler/basecamp.spec.ts` — a valid magic-link token drives the real `/auth/callback` and lands an authenticated, linked traveler on `/basecamp` (the browser-level "click the link" step, minus real delivery).

**Given** an advisor signed in to Command Center, and an email with no account yet,

**When**
1. the advisor invites the new user by email;
2. the user receives an email containing a code-free sign-in link;
3. the user clicks the link.

**Then**
- the user is authenticated automatically (no separate password/code step);
- the user lands directly in the onboarding flow ([ONB-2](#onb-2--new-user-completes-the-onboarding-flow));
- the advisor's client list/detail shows the invitee as `pending` (welcome sent, not yet signed in) until first sign-in, then `active` with an `accepted_at`.

**Notes / gaps**
- ⛔ **Step 2 (real email delivery) is not automatable over HTTP** — the link is emailed
  and never returned by the API. `test_traveler_signs_in_via_magic_link` is a documented
  skip awaiting the F2 SMTP/mailbox harness. Playwright instead mints the token directly
  and drives `/auth/callback`, so the *token → callback → landing* path is covered but the
  *inbox delivery* is not.
- 🔎 **"Lands in the *onboarding* flow" is not yet asserted.** `basecamp.spec.ts` only
  checks the first-prompt composer is visible — it does not distinguish a never-onboarded
  new user's basecamp from a returning user's. That distinction is [ONB-2](#onb-2--new-user-completes-the-onboarding-flow)'s gap.
- **Net-new test worth adding:** an *advisor-side* Playwright flow (invite a client from the
  Command Center UI and see them appear as `pending`) — today the invite is only exercised
  through the API/SDK, never the advisor's browser.

---

## ONB-1A · Invitee already has an account

- **Status:** 🚧 Planned
- **Personas:** Advisor
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** Advisor is signed in. The target email already has an account.
- **Automated by:** — &nbsp;·&nbsp; **Related:** `flows.ensure_client()` resolves a 409 email
  collision to the existing client, but no test asserts the *advisor-facing* "already
  registered" response or the last-sign-in detail.

**Given** an advisor signed in to Command Center, and an email that already has an account,

**When** the advisor tries to invite that email,

**Then**
- the system recognizes the account already exists and tells the advisor the user is already registered;
- the advisor can choose to resend the invitation or contact the user directly;
- the advisor UI shows registration details for that user, including whether/when they last signed in.

**Notes / gaps**
- **True gap.** The idempotent-create *helper* swallows the collision, but the product
  behavior in this scenario — the advisor being *told*, and seeing last-sign-in state — is
  unverified. Good candidate for an API test on the 409 shape **plus** a thin advisor-UI test.

---

## ONB-1B · Invitee never receives the email

- **Status:** 🟡 Partial
- **Personas:** Advisor
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** Advisor is signed in. A user was invited but did not receive the email.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar1_invite_e2e.py::test_advisor_can_resend_welcome_to_pending_client` — resending the welcome link to a pending client (the advisor nudge; 204 no-op).

**Given** an advisor whose invited user reports never receiving the email,

**When** the advisor opens that user and chooses to recover delivery,

**Then**
- the advisor can resend the invitation, or contact the user directly;
- when the user's provider is simply blocking the email, the advisor can obtain a
  code or link to send to the user out-of-band so they can still complete onboarding.

**Notes / gaps**
- ✅ Resend is covered at the API seam.
- ⛔ **Out-of-band recovery (advisor gets a shareable code/link) is not covered** — same
  SMTP-boundary limitation as ONB-1. Whether the API even exposes a fetchable link for the
  advisor to relay is an open product question to settle before writing this test.

---

## ONB-2 · New user completes the onboarding flow

- **Status:** 🟡 Partial
- **Personas:** Traveler (with Advisor verification)
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** An authenticated user who has never completed onboarding.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar2_dream_profile_e2e.py::test_dream_turn_persists_and_keeps_graph_sound` — a chat turn persists and the graph stays sound (invariants, not wording).
  - `apps/cli/tests/e2e/test_pillar2_dream_profile_e2e.py::test_conversation_grows_the_profile` — self-disclosure adds Profile/Dossier facts the advisor can see (**skips against the mock agent**; real growth verified against Bedrock).
  - `apps/cli/tests/e2e/test_pillar2_dream_profile_e2e.py::test_agent_never_surfaces_private_context_in_prose` — the Dossier/OSINT redaction wall holds.
  - `apps/web/e2e/onboarding/onboarding.spec.ts` → *"ONB-2: a never-onboarded traveler lands on the onboarding opener"* — the new-user `first_prompt` variant renders in the browser.

**Given** an authenticated, never-onboarded user arriving at basecamp,

**When**
1. the user sees the new-user basecamp experience (distinct from the returning-user one);
2. the user is prompted into the onboarding flow — a chat with the AI concierge that
   sets up their profile, preferences, and any necessary integrations;
3. the user completes the flow.

**Then**
- on completion the user is taken to the standard basecamp experience with their
  information and preferences populated (their Dossier);
- the advisor sees accurate Dossier information for that user in Command Center,
  including preferences/integrations captured during onboarding;
- the user is marked "onboarded" and is not prompted through the flow again.

**Notes / gaps**
- ✅ The **chat → Dossier growth** substance is covered by Pillar 2 (advisor-visible facts,
  redaction), so the *data* outcome of onboarding is well-tested at the API seam.
- ✅ **The new-user landing is now browser-tested** (`onboarding.spec.ts`). `/basecamp`
  server-renders one of three variants (see [basecamp/page.tsx](../../apps/web/app/basecamp/page.tsx)):
  `first_prompt` (the new-user single-prompt card with a seeded opener + "Begin in your own
  words…" composer), `post_first_touch`, and `with_itineraries`.
- ⚠️ **The "onboarded" model is `has_prior_session`, not a completeness flag.** A user is
  re-shown the first-prompt opener until *any* traveler session has ever existed (a real turn
  **or** a Skip/Close). There is no "Dossier complete" threshold — read the `Then` wording
  ("marked onboarded on completion") as this simpler "has conversed once" semantic.
- 🔍 **The positive-completion browser path is Bedrock-gated.** Asserting *engage → profile facts
  recorded → no reminder* needs a real tool-using agent (the mock records no facts — the Pillar 2
  lesson). The mock-safe landing is what the web test covers; fact-growth is covered at the API
  seam by Pillar 2.
- Related: skipping mid-flow is [ONB-2A](#onb-2a--user-skips-the-onboarding-flow).

---

## ONB-2A · User skips the onboarding flow (nudge)

- **Status:** ✅ Automated
- **Personas:** Traveler
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** A user on the first-prompt onboarding opener ([ONB-2](#onb-2--new-user-completes-the-onboarding-flow)).
- **Automated by:**
  - `apps/web/e2e/onboarding/onboarding.spec.ts` → *"ONB-2A: skipping onboarding surfaces the finish-your-introduction reminder"* — skip via "Not now" → basecamp shows the reminder, and the opener is not re-shown.
  - `apps/api/tests/test_me.py::test_onboarding_session_reports_profile_facts_presence` — the `has_profile_facts` signal that drives the nudge (false until a non-redacted profile fact exists; a redacted fact does not count).

**Given** a user on the onboarding opener who has told us nothing yet,

**When** the user skips the flow (the "Not now" / "Close" affordance),

**Then**
- the user is taken to the basecamp experience (`post_first_touch`);
- the system treats their profile as incomplete — derived from **no non-redacted profile facts** recorded (`has_profile_facts == false`), not a stored Dossier-completeness flag;
- basecamp shows a gentle "finish your introduction" reminder (the "Tell us how you travel" nudge) instead of the welcoming empty-itineraries state, pointing back to the always-open thread.

**Notes**
- **Built as part of this scenario** (product decision: skip-and-nudge is the intended UX).
  `POST /onboarding/dismiss` writes a marker session so `has_prior_session` flips true
  ([onboarding.py](../../apps/api/app/routers/onboarding.py)); `GET /me/onboarding_session`
  now returns `has_profile_facts` ([me.py](../../apps/api/app/routers/me.py)); basecamp swaps in
  the reminder when `post_first_touch && !has_profile_facts`
  ([BasecampShell.tsx](../../apps/web/app/basecamp/_components/BasecampShell.tsx)).
- 🔍 **The recovery path (skip → later engage → reminder clears) is Bedrock-gated** — clearing
  the nudge requires the agent to actually record a profile fact, which the mock won't do. The
  *signal* itself (facts present → no reminder) is unit-tested at the API seam.
- The scenario title changed from "cancels" to "skips" to match the product's own affordance
  labels ("Not now" / "Close") and the built behavior.

---

## ONB-3 · User adjusts preferences after onboarding

- **Status:** 🟡 Partial
- **Personas:** Traveler (with Advisor verification)
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** An already-onboarded user.
- **Automated by:**
  - `apps/cli/tests/e2e/test_pillar4_details_vault_e2e.py::test_traveler_self_service_party_member` — traveler maintains their own household via `/me` (`created_by_actor == "traveler"`); advisor sees it.
  - `apps/cli/tests/e2e/test_pillar4_details_vault_e2e.py::test_passport_upload_to_vault_with_expiry_flag` — traveler self-serves documents; advisor sees the same record.

**Given** an onboarded user,

**When** the user updates their profile and preferences,

**Then**
- the updates are saved and reflected for the user;
- the advisor sees those updates in Command Center.

**Notes / gaps**
- ✅ The **"traveler self-edits, advisor sees it"** shape is covered for party members and
  vault documents.
- 🔎 **General preference editing** (travel style, dietary/mobility constraints — i.e.
  Profile/Dossier facts the traveler changes) is only ever *seeded by tests*, never driven by
  a traveler self-edit. If there's a traveler-facing preferences editor, it's untested; if
  there isn't one, this scenario is partly aspirational. Clarify the surface before extending.
