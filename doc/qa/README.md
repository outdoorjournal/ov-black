# QA Scenarios

Human-authored, product-level QA scenarios for OV Black — the **source spec** for
our end-to-end tests. Each file describes how a slice of the product should behave
from a user's point of view; each scenario is written so it maps cleanly onto an
automated e2e test (and tracks whether that test exists yet).

This directory is the shared workspace where the product owner and Claude collaborate:
**you** write and refine scenarios in plain language; **Claude** turns them into
maintainable e2e tests and keeps each scenario's coverage status in sync.

These docs are *specs*, not tests — nothing here runs. The tests they drive live in
the existing e2e harnesses (see [Where the tests live](#where-the-tests-live)).

## How we work in here

1. **You author a scenario** (or edit an existing one) in the relevant area file,
   using the [template](#scenario-template) below. Prose is fine — the `Then`
   bullets are what become assertions, so make each one a single observable outcome.
2. **You ask Claude to implement one or more scenarios** by ID (e.g. "write the e2e
   test for ONB-1 and ONB-2A").
3. **Claude implements the test(s)** in the right harness, references the scenario ID
   in the test name, then updates that scenario's **Status** and **Automated by**
   fields (and the "Coverage at a glance" table) so the doc and the tests never drift.
4. **When behavior changes**, update the scenario first; the failing/soon-to-fail test
   follows from it.

Keep the round-trip tight: one scenario ≈ one test (or one `describe`/test-class).
That 1:1 mapping is what keeps this maintainable as we add areas.

## File & ID conventions

- **One file per feature area**, named after the area (e.g. `onboarding.md`). Add new
  areas as new files and list them in [Scenario areas](#scenario-areas) below.
- **Every area has a short code** (Onboarding → `ONB`). Scenarios are numbered within
  the area: `ONB-1`, `ONB-2`, …
- **Alternative / branch flows** hang off their parent with a letter suffix:
  `ONB-1A`, `ONB-1B` are variants of `ONB-1`.
- **IDs are stable and never reused.** If a scenario is retired, leave the ID with a
  ~~strikethrough~~ note rather than renumbering — tests, commits, and discussion
  reference these IDs.
- Each area file opens with a one-line purpose, a link back to this README, and a
  **Coverage at a glance** table.

## Scenario template

Copy this block for a new scenario:

```markdown
## <ID> · <Short title>

- **Status:** 🚧 Planned
- **Personas:** <who drives it, e.g. Advisor → Traveler>
- **Surface:** <Web UI (Playwright) | API seam (CLI/pytest) | both>
- **Preconditions:** <state that must exist before the scenario starts>
- **Automated by:** <path/to/test::name, or — >

**Given** <starting state>,

**When**
1. <action>;
2. <action>.

**Then**
- <observable, assertable outcome>;
- <observable, assertable outcome>.

**Notes** (optional) — anything that can't be automated yet, edge cases, or
cross-references to related scenarios.
```

Why Given / When / Then: **Given** sets up fixtures/preconditions, **When** is the
driver script, and each **Then** bullet is one assertion. That's exactly the shape a
test wants, so translation is mechanical and review is easy.

**Write `Then` bullets as invariants, not narration.** The existing e2e suite's
guiding rule is *assert on what changed, never on wording*: a status transition
(`pending → active`), a fact row appearing, a graph staying structurally sound, a
guarantee holding (an unknown email returns the same 204 as a real one). Prefer
"the invitee shows as `pending` until first sign-in" over "the advisor sees a
success message." Invariant assertions stay green whether the agent runs against
the deterministic mock or real Bedrock; wording assertions are flaky by design.

## Status legend

| Badge | Meaning |
| --- | --- |
| 🚧 Planned | Scenario written; no automated test yet. |
| 🟡 Partial | Some `Then` bullets are covered; others are skipped or manual (say which in **Notes**). |
| ✅ Automated | Fully covered by a passing e2e test linked in **Automated by**. |
| 🔍 Manual only | Not automatable with the current harness (e.g. real email delivery). Explain why in **Notes**. |

Keep **Status**, **Automated by**, and the area's **Coverage at a glance** table
consistent — they're the at-a-glance health of the suite.

**Honest skips, not false green.** The e2e suites never quietly pass a gate they
can't exercise — they `skip` with a reason: a milestone not yet built (`skip_until`
with the slice coordinate), the mock agent making no tool calls, no payment gateway
wired, a provider lane dark for lack of credentials, the SMTP/mailbox harness
absent. Mirror that here: if a `Then` bullet can only be checked under conditions
we don't have, mark the scenario 🔍 (or 🟡 with the bullet flagged in **Notes**) and
name the gate — don't claim ✅. A documented skip is coverage information; a
false-green is a lie the suite tells later.

## Choosing a surface / harness

We have two complementary e2e harnesses. Pick per scenario (a scenario can use both):

- **Web UI → Playwright** (`apps/web/e2e/`). Use when the outcome is something a user
  *sees or clicks* — the onboarding chat, basecamp reminders, Command Center views.
  Personas (`advisor`, `traveler`, `public`) come with pre-captured sessions; a
  scenario's **Personas** field usually names the Playwright project to run under.
- **API seam → CLI/pytest** (`apps/cli/tests/e2e/`, driven by the `ovb` CLI/SDK). Use
  when the outcome is a *state change or contract* — a client becomes `pending`/`active`,
  a Dossier fact is written, an enumeration guarantee holds. Faster and less flaky than
  a browser, so prefer it whenever the UI isn't the thing under test.

Rule of thumb: assert **state** at the API seam, assert **experience** in the browser.
Many scenarios are cleanest as an API test for the data outcome plus a thin Playwright
test for the visible result.

## The pillar suite is the existing scenario spine

Before writing a scenario as if it's greenfield, check `apps/cli/tests/e2e/`. The
CLI/pytest suite is already organized as end-to-end **pillars** (`test_pillar1_invite`
… `test_pillar6_invoice_book`, stitched together in `test_full_loop_e2e.py`) that trace
the whole concierge-to-confirmed demo loop. Much of a new area is often *already
automated at the API seam* by a pillar — so a QA scenario's job is usually to **cite
that coverage and target the gaps**, not to re-specify it.

Concretely, when reconciling an area:

- **Map each scenario onto the pillar(s) that touch it** and put the exact
  `path::test_name` in **Automated by**. (Onboarding, e.g., leans on Pillar 1 for
  invite/enumeration and Pillar 2 for the dream/Dossier chat.)
- **The gaps are where new tests earn their keep** — and they cluster predictably:
  - *UI states the API can't show* — an advisor-facing "already registered" message, a
    new-user vs. returning basecamp, an onboarding-complete flag, a reminder banner.
    These want a thin Playwright test, since the pillar suite is headless.
  - *The email/SMTP boundary* — the emailed magic-link click and any "resend / get a
    shareable link" recovery never cross the HTTP seam. Automatable only with the F2
    mailbox harness; until then they're 🔍.
  - *Mock-limited assertions* — anything depending on the agent making real tool calls
    (profile growth, grounded-not-generic replies) self-skips against the mock and is
    only truly exercised against Bedrock (F3 UAT).
- **Don't duplicate a green pillar test in Playwright** just to have a browser version.
  Add a UI test only when the *visible experience* is the thing under test.

## Linking tests back to scenarios

So the two stay navigable in both directions:

- **Name the test after the scenario ID.** Playwright: `test("ONB-1: advisor invites a
  new user", …)` (or a `test.describe("ONB-1", …)`). Pytest: put the ID in the test's
  docstring/name.
- **Point the scenario at the test.** Fill **Automated by** with the clickable path,
  e.g. `apps/web/e2e/traveler/onboarding.spec.ts`.

## Where the tests live

This directory intentionally does **not** duplicate run instructions — the harnesses
own those:

- **Playwright web e2e:** [`apps/web/e2e/README.md`](../../apps/web/e2e/README.md) —
  layout, personas, magic-link auth, and how to run local vs. staging.
- **CLI/pytest e2e:** [`apps/cli/README.md`](../../apps/cli/README.md) and the
  `apps/cli/tests/e2e/` suite (`test_pillar*_e2e.py`) — the `ovb`-driven API flows.

Both are explicitly outside `pnpm test` / CI: they need a running stack and are invoked
on purpose (see the READMEs above and the root [`CLAUDE.md`](../../CLAUDE.md) "Driving
the live app" section).

## Scenario areas

| Area | Code | File |
| --- | --- | --- |
| Onboarding | `ONB` | [onboarding.md](./onboarding.md) |
| Itinerary Builder | `ITB` | [itinerary-builder.md](./itinerary-builder.md) |

_Add a row when you start a new area file._
