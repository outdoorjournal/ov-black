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
| [ONB-1](#onb-1--advisor-invites-a-new-user) | Advisor invites a new user | ✅ Automated | advisor invites via UI → **Pending** → sign-in → **Active** (web) + P1 (API); real email delivery still 🔍 |
| [ONB-1A](#onb-1a--invitee-already-has-an-account) | Invitee already has an account | ✅ Automated | repeat invite → advisor sees "already exists" (web) |
| [ONB-1B](#onb-1b--invitee-never-receives-the-email) | Invitee never receives the email | 🟡 Partial | advisor "Nudge" re-send (web) + P1 (API); out-of-band code/link recovery still 🔍 |
| [ONB-2](#onb-2--new-user-completes-the-onboarding-flow) | New user completes the onboarding flow | 🟡 Partial | new-user landing + **live concierge turn** (web) + P2 dream/profile (API); semantic completion agent-gated |
| [ONB-2A](#onb-2a--user-skips-the-onboarding-flow) | User skips the onboarding flow (nudge + milestone) | ✅ Automated | skip→reminder (web) + `evaluate_onboarding` rule/`onboarding_complete` (API) + milestone card; live completion agent-gated |
| [ONB-3](#onb-3--user-adjusts-preferences-after-onboarding) | User adjusts preferences after onboarding | 🟡 Partial | traveler party self-edit → advisor sees (web) + P4 (API); general-preferences editor still absent |

---

## ONB-1 · Advisor invites a new user

- **Status:** ✅ Automated (browser-driven; real email delivery still 🔍)
- **Personas:** Advisor → Traveler
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** Advisor is signed in. The target email has no existing account.
- **Automated by:**
  - `apps/web/e2e/advisor/onboarding-invite.spec.ts` → *"ONB-1: advisor invites a new user → Pending, then Active after first sign-in"* — the advisor fills the **New Client** form, the roster shows the invitee as **Pending**, the traveler then signs in via their link and the same row flips to **Active** (API-seam backstop confirms `access_status` and `accepted_at`).
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
- ✅ **The advisor-side browser flow now exists** (`onboarding-invite.spec.ts`): the invite is
  driven through the Command Center UI and the roster's `pending` → `active` transition is
  asserted in the browser (with an API-seam backstop), not only through the SDK.

---

## ONB-1A · Invitee already has an account

- **Status:** ✅ Automated (advisor-facing "already exists" message)
- **Personas:** Advisor
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** Advisor is signed in. The target email already has an account.
- **Automated by:**
  - `apps/web/e2e/advisor/onboarding-invite.spec.ts` → *"ONB-1A: inviting an already-registered email tells the advisor it exists"* — the first invite creates the account (the fixture); a second invite of the same email surfaces **"A client with this email already exists."** and stays on the form (no duplicate). &nbsp;·&nbsp; **Note:** the *last-sign-in detail* bullet below is not yet asserted in the browser.

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
  - `apps/web/e2e/advisor/onboarding-invite.spec.ts` → *"ONB-1B: advisor can re-send the welcome link to a pending invitee"* — the advisor clicks **Nudge** on a pending row and sees **"Welcome link re-sent."**
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
  - `apps/web/e2e/traveler-flows/chat.spec.ts` → *"ONB-2: a traveler converses with the concierge from the opener"* — the traveler types a self-disclosure into the opener, sends it, and a concierge reply streams back (turn loop asserted structurally: the composer re-enables once the reply settles, no D015 error row) — a **live turn against the local agent**, not a skip.

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
- ✅ **The chat interaction is now browser-tested** (`chat.spec.ts`): a real turn is driven from
  the opener and a reply streams back. What remains agent-gated is the *semantic completion* —
  asserting *engage → profile facts recorded → no reminder / milestone fires* needs the agent to
  actually record a fact via a tool call. That fact-growth is verified at the API seam by Pillar 2;
  the browser proves the turn **loop** works, never the wording.
- Related: skipping mid-flow is [ONB-2A](#onb-2a--user-skips-the-onboarding-flow).

---

## ONB-2A · User skips the onboarding flow (nudge)

- **Status:** ✅ Automated
- **Personas:** Traveler
- **Surface:** Web UI (Playwright) + API seam (pytest)
- **Preconditions:** A user on the first-prompt onboarding opener ([ONB-2](#onb-2--new-user-completes-the-onboarding-flow)).
- **Automated by:**
  - `apps/web/e2e/onboarding/onboarding.spec.ts` → *"ONB-2A: skipping onboarding surfaces the finish-your-introduction reminder"* — skip via "Not now" → basecamp shows the reminder, and the opener is not re-shown.
  - `apps/api/tests/test_me.py::test_evaluate_onboarding_rule` — the one swappable completeness rule in isolation.
  - `apps/api/tests/test_me.py::test_onboarding_session_reports_onboarding_complete` — the `onboarding_complete` verdict the rule produces (false until satisfied; a redacted fact doesn't count).
  - `apps/web/tests/basecamp/milestoneCard.test.tsx` — the milestone card renders only for a `milestone` turn.

**Given** a user on the onboarding opener who has told us nothing yet,

**When** the user skips the flow (the "Not now" / "Close" affordance),

**Then**
- the user is taken to the basecamp experience (`post_first_touch`);
- the system treats them as not-yet-onboarded — derived from the server's **`onboarding_complete`** verdict being false, computed by the single `evaluate_onboarding` rule (today: ≥1 non-redacted profile fact), **not** a scattered fact check;
- basecamp shows a gentle "finish your introduction" reminder instead of the welcoming empty-itineraries state, pointing back to the always-open thread.

**Notes**
- **One rule, two reactions.** The completeness criterion lives in exactly one place —
  `evaluate_onboarding` ([me.py](../../apps/api/app/routers/me.py)) — exposed as
  `onboarding_complete`. The basecamp nudge gates on `!onboarding_complete`, and the in-chat
  **milestone card** fires the moment that same verdict flips true. Raising the bar (e.g. two
  facts **plus** a known age) is a change to that one function; no nudge/card/UI edits follow.
- **Milestone card (the "something interesting happened" signal).** A celebratory card
  ([OnboardingMilestoneCard](../../apps/web/app/chat/[client_id]/_components/OnboardingMilestoneCard.tsx))
  drops into the chat when onboarding completes — replacing dense agent prose with one visual
  beat. RightRailChat detects the flip via a post-turn `router.refresh()` (which also clears the
  nudge); SinglePromptCard (first-touch, can't refresh without unmounting) polls
  `GET /me/onboarding_session` after each turn. `commitMilestone` is fire-once.
- `POST /onboarding/dismiss` writes a marker session so `has_prior_session` flips true
  ([onboarding.py](../../apps/api/app/routers/onboarding.py)), landing the skipper in
  `post_first_touch`.
- 🔍 **The completion path (engage → rule satisfied → nudge clears + milestone fires) is
  Bedrock-gated** end-to-end — it needs the real agent to record a profile fact, which the mock
  won't. The rule, the `onboarding_complete` verdict, and the card render are all unit-tested;
  only the live round-trip awaits the agent.
- The scenario title changed from "cancels" to "skips" to match the product's own affordance
  labels ("Not now" / "Close") and the built behavior.

---

## ONB-3 · User adjusts preferences after onboarding

- **Status:** 🟡 Partial
- **Personas:** Traveler (with Advisor verification)
- **Surface:** Web UI (Playwright) + API seam (CLI/pytest)
- **Preconditions:** An already-onboarded user.
- **Automated by:**
  - `apps/web/e2e/traveler-flows/preferences.spec.ts` → *"ONB-3: a traveler's party edit is visible to their advisor"* — the traveler adds a party member with a dietary need on `/basecamp/party`, and the **advisor sees that same member** on the Command Center client-detail page (both sides driven in the browser).
  - `apps/cli/tests/e2e/test_pillar4_details_vault_e2e.py::test_traveler_self_service_party_member` — traveler maintains their own household via `/me` (`created_by_actor == "traveler"`); advisor sees it.
  - `apps/cli/tests/e2e/test_pillar4_details_vault_e2e.py::test_passport_upload_to_vault_with_expiry_flag` — traveler self-serves documents; advisor sees the same record.

**Given** an onboarded user,

**When** the user updates their profile and preferences,

**Then**
- the updates are saved and reflected for the user;
- the advisor sees those updates in Command Center.

**Notes / gaps**
- ✅ The **"traveler self-edits, advisor sees it"** shape is now covered **in the browser** for
  party members (`preferences.spec.ts`), plus the party/vault API-seam coverage.
- 🔎 **General preference editing** (travel style, free-text Profile/Dossier facts the traveler
  changes) has **no traveler-facing editor today** — the household roster + vault are the only
  self-service surfaces. That slice of ONB-3 stays aspirational until a preferences editor exists;
  the party-member edit is the drivable stand-in the browser test uses.
