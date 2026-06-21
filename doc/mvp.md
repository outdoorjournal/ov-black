# Outdoor Voyage: Black — MVP Definition

> Companion to [prd.md](./prd.md) (product brief), [TravelGraph_Analysis.md](../apps/agent/src/agent/ai/TravelGraph_Analysis.md)
> (graph refactor), and [mvp-plan.md](./mvp-plan.md) (the slice-by-slice plan to build this).
> This file is the **scope contract** for the MVP — what "done" means. The plan is how we get there.

---

## 1. What the MVP is

The MVP is the **full concierge-to-confirmed loop**: a traveler is invited, dreams with the agent
while their profile fills in, staff assemble a delightful itinerary from real multi-source inventory,
the traveler supplies their party details and documents, AI lets them fork alternate versions that
staff reconcile against reality, and the trip is paid for via invoices and booked — with booked
inventory locked against further change.

M001 already shipped the **front half** of this loop (invite → dream → draft → advisor approval →
client itinerary view). The current `feat/travelgraph-schema-spine` branch has rebuilt the itinerary
graph into a far richer spine (first-class time/space, typed cards, a reusable card library, a
server-side linearization service). The MVP closes the **back half** — multi-source build, traveler
details + vault, fork/reconcile, and money — and finishes the integrations that are still stubs.

### The loop in one picture

```
  ┌─────────┐   ┌──────────┐   ┌─────────┐   ┌──────────┐   ┌───────────────┐   ┌──────────────────┐
  │ 1 INVITE │→ │ 2 DREAM  │→ │ 3 BUILD │→ │ 4 DETAIL │→ │ 5 FORK &      │→ │ 6 INVOICE & BOOK  │
  │          │   │          │   │         │   │          │   │   RECONCILE   │   │                   │
  └─────────┘   └──────────┘   └─────────┘   └──────────┘   └───────────────┘   └──────────────────┘
  advisor seeds  traveler chats  staff + AI    traveler adds  traveler forks      advisor issues
  Voodoo Doll,   → profile +     assemble from  party members  with AI; staff      invoice(s) totalling
  issues invite, mood-board       OV + Places +  + uploads      diff vs. reality    booked inventory;
  traveler       cards from       Duffel +       passports to   & reconcile;        traveler pays;
  redeems        real inventory   Ratehawk;      the vault      booked/finalized    paid nodes → booked
  magic link                     advisor         (reusable)     nodes are immutable → confirmed
                                  approves
```

Each stage maps to one of the seven capabilities you named. Stages 5 and 6 interlock through the
node lifecycle and the money gate (see §4).

---

## 2. The seven capability pillars

For each: **what it means**, **acceptance criteria** (what proves it's done), and **status today**.

### Pillar 1 — A traveler can be invited
**Means:** An advisor creates a client, hand-seeds the Voodoo Doll, and issues an invite; the
traveler redeems an emailed magic link and lands in their chat. No self-serve signup.

**Acceptance**
- Advisor creates client + Voodoo Doll in Command Center; invite is issued (single-use, lifecycle-tracked).
- Traveler redeems magic link → role-aware redirect into `/chat/[client_id]`.
- Invite cannot be redeemed twice; unknown code/wrong email collapse to one indistinguishable response.

**Status: ✅ built (M001/S01–S03 + migration 0007 invite lifecycle).** Owed: real staging deploy +
SMTP, founder UAT.

### Pillar 2 — A traveler can express dreams and build their profile
**Means:** The traveler chats with the agent; the agent opens from a grounded observation, adapts to
how they arrive (named dream vs. vague), proposes inventory-backed cards, and **writes new knowledge
back into the three context tiers** (Profile = traveler-told, Dossier = agent-inferred private, OSINT
= research, never surfaced) so the profile genuinely grows from the conversation.

**Acceptance**
- Agent's first message is specific and grounded, not generic (R003).
- During conversation the agent records `record_profile_fact` (traveler-told) and `record_dossier_inference`
  (private) facts; advisor sees them update in the client detail tabs.
- Mood-board cards render from real inventory with pin / keep / discard that persists across reloads.

**Status: ✅ largely built (M001/S04–S07 + migrations 0010–0013 + `apps/agent` runtime with
`record_profile_fact` / `record_dossier_inference` tools).** Owed: founder craft-feel UAT against real
Bedrock; verify the agent actually drives profile growth in live conversation.

### Pillar 3 — Staff build a delightful itinerary fast, from multiple real sources
**Means:** Staff (with heavy AI assistance) assemble an itinerary quickly, drawing on **OV inventory,
Google Places (e.g. places to eat), Duffel (flights), and Ratehawk (hotels)** — using the card-template
library, AI assembly, and AI gap-filling, so the result delights and is grounded in real availability.

**Acceptance**
- The agent's source-agnostic `search_inventory` / `get_inventory_detail` tools dispatch to **four live
  adapters**: OV (done), Google Places (live), Duffel (live), Ratehawk (live).
- An advisor can build an itinerary in minutes: instantiate from the card-template deck, drop in
  inventory cards, and run **AI Fill** to populate gaps with physically-feasible options.
- Server-side **linearization** drives every rendered surface (no per-view re-derivation).
- Every inventory-sourced node carries `source` + `source_id` provenance and is rendered with attribution.

**Status: 🔨 partial.** OV provider built; **Google Places / Weather / Flight-status are stubs**;
**Duffel and Ratehawk do not exist**. Card-template library + Japan seed + linearization service landed
on the branch. **AI Fill (Phase 6) and Analyze (Phase 5) are documented but not implemented.** No
first-class numeric node cost yet (needed downstream for invoicing).

### Pillar 4 — Traveler enters party details and stores documents securely
**Means:** The traveler completes all missing details for their **travel party** (each member's
identity, DOB, dietary/medical/mobility, loyalty numbers, emergency contact) and uploads sensitive
**documents (passport photos, visas)** to a secure vault, stored encrypted and **reusable across future
trips**.

**Acceptance**
- Traveler-facing form captures party members + per-member detail; data persists to the parties/travelers
  model and is visible to the advisor.
- Vault supports encrypted upload (passport, visa, insurance, loyalty, other), access-controlled to the
  client + assigned advisor, with **expiry tracking** (flag passports valid < 6 months).
- Documents are stored once and **re-attachable to a later trip** (not re-uploaded per itinerary).

**Status: 🔨 not built.** The graph-structural `parties` / `travelers` tables exist (migration 0014)
but carry no member-identity/document model, no traveler-facing entry surface, and there is **no vault
/ secure document storage** (S3 + encryption + expiry) anywhere in the codebase.

### Pillar 5 — Traveler forks with AI; staff reconcile; booked nodes are immutable
**Means:** The traveler can ask AI to produce an **alternate version of an itinerary** (a "fork" — like a
branch). Staff work with the **difference** between the fork and the live plan, checking it against
reality and folding accepted changes back in. **Nodes that are booked/finalized cannot be edited** in
either the live plan or a fork — they carry over locked.

**Acceptance**
- A traveler (via the agent) can fork an approved itinerary into an alternate version; AI mutates the fork.
- Staff get a **diff view** (fork vs. baseline): added / removed / changed / moved nodes, side by side.
- Staff **reconcile**: accept individual changes into the live plan, or discard them, after checking
  feasibility (via Analyze).
- A `booked` or `confirmed` node is **immutable** — edits by traveler or agent are refused with a crafted
  explanation; only an advisor can move it, and only through an explicit demotion/cancellation flow.

**Status: 🔨 not built.** No fork/version concept; no diff/reconcile surface; **status-aware mutation
gates (Phase 7) are design-only** — today a `booked` node can be re-titled by anyone holding the editor
lock. The graph does have `is_selected_alt` / `alternative_to` for *local* swaps, but not whole-itinerary
forking with reconcile.

### Pillar 6 — One or more invoices total all booked inventory
**Means:** The system can issue **one or more invoices** to the traveler(s). Collectively the invoices
**total exactly the booked inventory**. A node must be **paid for before we book it** on our side.

**Acceptance**
- Bookable nodes carry a **first-class numeric cost + currency** (not free-text metadata).
- An advisor can group approved bookable nodes into **one or more invoices** (e.g. deposit + balance, or
  per-supplier); each invoice's total = sum of its line items, and line items reference the nodes they pay for.
- The traveler can view and **pay invoices** (Braintree per PRD; see Decision D-PAY).
- **Money gate:** a node may only move `approved → booked` when it is covered by a paid (or at minimum
  issued) invoice line. A reconciliation check proves: Σ(paid invoice lines for nodes) accounts for
  Σ(booked node costs) — no booked inventory is unpaid, no double-billing.
- The traveler sees invoice + payment history.

**Status: 🔨 not built.** No invoices, line items, payment integration, node cost, or money gate exist.

---

## 3. Capability → current-state summary

| # | Pillar | Built | Partial | Not started |
|---|--------|:---:|:---:|:---:|
| 1 | Invite | ● | | |
| 2 | Dream + profile build | ● | (UAT) | |
| 3 | Multi-source fast build | | OV + templates + linearization | Places-live, Duffel, Ratehawk, AI Fill, node cost |
| 4 | Party details + vault | | parties/travelers tables | member model, traveler UI, vault/docs/expiry |
| 5 | Fork + reconcile + immutability | | local alt edges | fork/version, diff/reconcile, status gates |
| 6 | Invoicing + pay-before-book | | | node cost, invoices, line items, Braintree, money gate |

---

## 4. The spine that ties pillars 3/5/6 together: the node lifecycle + money gate

Pillars 5 and 6 are not independent features — they're two faces of one **status state machine** on
graph nodes. Getting this right is the load-bearing design of the MVP.

```
 idea ──► proposed ──► approved ──►[ MONEY GATE ]──► booked ──► confirmed
   │          │            │                            │            │
   └──────────┴────────────┘                            │            │
   freely editable by traveler / agent / advisor        │            │
                                                         ▼            ▼
                              immutable except advisor demotion / cancellation flow

 discarded  ◄── reversible side-state from any pre-booked status
```

**Editability gates (Pillar 5):**
- `idea`, `proposed` — editable by traveler, agent, advisor.
- `approved` — advisor must demote to `proposed` before editing; agent/traveler cannot edit directly.
- `booked`, `confirmed` — **immutable**; only an advisor, only via an explicit demotion/cancellation flow
  (which writes a visible `node_history` note). Forks carry these over locked.

**Money gate (Pillar 6):** a node transitions `approved → booked` **only** when a paid (or issued, per
Decision D-PAY) invoice line covers its cost. Money lives in the invoice tables, not in node status, so
there is a single source of truth for "what's been paid." The reconciliation invariant — booked inventory
⇔ paid invoice lines — is enforced/asserted at the service layer.

**Fork interaction (Pillar 5):** a fork is a versioned clone of the graph. Pre-booked nodes copy in as
editable; `booked`/`confirmed` nodes copy in **locked** (you cannot fork away a paid booking). Reconcile
is a node-by-node diff between the fork and its baseline, gated by Analyze feasibility before accept.

---

## 5. Explicitly out of scope for this MVP

Carried from PRD §5 plus refactor-era deferrals:

- WhatsApp / iMessage channels (in-app chat only for MVP). *(R050 deferred.)*
- Native mobile app, printed magazine, multi-traveler Voodoo Dolls.
- Automated supplier booking — **advisors book manually**; the system records confirmations back into the graph.
- Experience/train **auto-booking** (present options, book manually).
- Live Analyze "deep" mode external calls (real-time traffic/flight/currency) beyond what Fill needs —
  ship Analyze shallow/standard; defer deep.
- TravelGraph **Meld/Extract** multi-party UI ops (Phase 8) — the parties model exists for vault/details,
  but per-party divergent-timeline merging is post-MVP.
- Template **drift detector** auto-Analyze (snapshot columns exist; the detector is post-MVP).
- PDF itinerary export (the in-app client itinerary view is the MVP surface; R058 deferred).

---

## 6. Key open decisions to lock

These shape the plan; recommendations carried into [mvp-plan.md](./mvp-plan.md) §6.

| ID | Decision | Recommendation |
|----|----------|----------------|
| **D-FORK** | Fork model: whole-itinerary versioned clone vs. in-graph alternatives. | **Versioned clone** (`itineraries.forked_from_id` + `nodes.forked_from_node_id` lineage) with a git-style diff/reconcile. In-graph `alternative_to` stays for *local* swaps only. |
| **D-PAY** | Payment vendor + whether `booked` needs *paid* vs. *issued* invoice. | **Braintree** (PRD-decided, reference impl in `voyage-site`). Gate on **paid** for the money invariant; allow advisor override to book on *issued* for trusted clients (logged). |
| **D-COST** | Where node cost lives. | New **first-class `nodes.cost_amount numeric` + `cost_currency`** columns; deprecate free-text `metadata.price` for bookables. Multi-currency handling minimal (store native; one display currency). |
| **D-VAULT** | Document storage + encryption. | **S3 + SSE-KMS**, presigned upload/download, access-scoped to client + assigned advisor; expiry tracked in Postgres. (PRD says client-side encryption; recommend SSE-KMS for MVP, client-side later.) |
| **D-ANALYZE** | How much of Phase 5 Analyze to build for the MVP. | Build **shallow + standard** depth only — enough to back AI Fill and fork-reconcile feasibility. Defer deep/real-time. |
| **D-BOOK** | How booking state + the repriceable supplier-offer lifecycle are modeled (esp. flights). | Two structured tables separate from node status: **`node_offers`** (transient time-boxed quotes — `expires_at`/`priced_at`/amount/refresh lineage) attached pre-booking, and **`bookings`** (committed record — supplier order/PNR, charged amount, links to the offer + covering invoice line). Flight offers are quotes valid only until `expires_at` and **re-priced before `approved → booked`**; the money gate reconciles against the re-priced amount and surfaces any price delta. Booking detail is never free-text `metadata`. See **D024** + draft schema in [mvp-plan.md](./mvp-plan.md) §8. |

---

## 7. MVP "done" — the demo script

The MVP is complete when this runs end-to-end in staging against **real Bedrock, real OV, real Google
Places, real Duffel, real Ratehawk, and real Braintree (sandbox)**, with the craft-feel line held
(R014/R021):

1. Advisor seeds a client + Voodoo Doll and sends an invite. Traveler redeems the magic link.
2. Traveler chats; agent opens grounded, proposes real cards, and the profile visibly grows.
3. Advisor + AI assemble a multi-day itinerary pulling a **flight (Duffel)**, **hotel (Ratehawk)**, an
   **OV experience**, and a **restaurant (Google Places)**; AI Fill closes a gap; advisor approves; the
   client sees the final itinerary.
4. Traveler enters party members and uploads a passport to the vault; advisor sees them.
5. Traveler asks AI for an alternate version; a fork is created and mutated; advisor opens the **diff**,
   checks feasibility, and reconciles selected changes into the live plan. A booked node refuses edits.
6. Advisor issues a **deposit invoice + balance invoice** totalling the booked inventory; traveler pays
   via Braintree sandbox; paid nodes flip to `booked`; advisor records supplier confirmations →
   `confirmed`. Invoice/payment history is visible. The reconciliation check passes: booked inventory ⇔
   paid invoice lines.

Mechanical tests **and** a founder craft-feel sign-off (R021) both gate completion.
</content>
</invoke>
