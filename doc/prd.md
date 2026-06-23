# Outdoor Voyage: Black — Product Requirements Document

## 1. Vision

An AI-native, invitation-only travel concierge for high-net-worth individuals. OV Black combines wholesale rates, curated local expertise, and exclusive inventory to deliver bespoke travel experiences that can't be found anywhere else.

**Design ethos:** Amex Black / Tesla S — clean, minimal, luxurious. The product should feel exclusive before the client ever speaks to anyone.

---

## 2. Target Customer

- High-net-worth individuals and couples (estimated $5M+ net worth)
- Typically travel as couples or small groups (family, close friends)
- Accustomed to premium service; expect trust, discretion, and polish
- Often have vague travel ideas rather than fully formed plans
- Value authentic cultural experiences, not just luxury hotels

**Example persona:** Affluent couple, art/culture/history enthusiasts, post-cruise travelers, community-active (Rotary, philanthropy). Budget ~$15K+ for a 6–10 day trip. They want a plan handed to them — validated, bookable, beautiful.

---

## 3. Core Concepts

### 3.1 The "Dossier" (Client Profile)

An AI-constructed deep profile of each client, built from:

- **Open-source intelligence:** Public records, press mentions, social profiles, SEC filings, estimated net worth
- **Stated preferences:** Preferred contact method, travel companions, group composition (solo/couple/family/friends), ages of children if applicable
- **Psychological profile:** Motivations and triggers that drive travel decisions:
  - FOMO
  - Social status / peer validation
  - Bucket list aspirations
  - Genuine passion (art, culture, history, UNESCO sites, adventure, mountains, cuisine, etc.)
- **Travel history:** Past trips, spend levels, what they loved vs. tolerated

The Dossier is a living document — it evolves with every interaction and trip.

We need methods of quickly adding to this profile over time, and using it to inform every recommendation. It’s the secret sauce for personalization at scale.

### 3.2 Necessary Friction

Not everything should be instant. A response that's too fast undermines trust with this clientele. The system introduces deliberate, thoughtful pacing — the feeling that real experts are crafting something just for you. This principle is concretely implemented in **Phase 3: The Build** (see Section 4).

Examples:
- "We're having our local expert review this for you"
- Offering a callback with a real person or on-the-ground contact
- Progress updates that build anticipation before the final reveal

### 3.3 Trust-Building Content

All recommendations must be validated with:

- Links to well-known editorial publications (Condé Nast Traveler, Travel + Leisure, etc.)
- Real photography — not stock
- Local expert attribution
- Real-time availability and pricing (not aspirational)

---

## 4. User Flow (MVP)

### Phase 1: Onboarding
1. Client receives invitation (link/code)
2. Arrives at a minimal, elegant landing page — logo + entry point
3. Selects preferred contact method: Email, WhatsApp, Call, iMessage, Other
4. Brief intake: who they are, who they travel with, what excites them
5. System begins building the Dossier (automated research + intake responses)

### Phase 2: Dreaming — The Mood Board

The client chats with an AI agent to explore what they want. As they talk, the UI builds a visual **mood board** in real time — a split-pane experience with conversation on one side and an evolving collection of cards on the other.

**How it works:**
1. Client starts with anything — a vague idea ("Como + Dolomites"), a bucket-list item, or just a mood ("something adventurous in Asia")
2. The AI agent engages conversationally, drawing on the Dossier to suggest things the client might love
3. As they chat, the UI dynamically adds **cards** to the mood board: destination photos, activity snapshots, maps, hotel options, notes, editorial links
   - *Example:* Client mentions climbing Mt. Fuji → a card with a stunning Fuji photo, best season info, and a trail overview appears on the board
4. The agent is **context-aware** — it knows weather, seasonality, and local constraints (e.g., no sailing in Michigan in winter, monsoon season in Southeast Asia, Japan is rainy in June) and steers accordingly
5. The agent **proactively suggests** experiences based on the Dossier and the emerging mood board — not just responding, but inspiring

**Client controls on the mood board:**
- **Must Do** — pin a card as non-negotiable for the final itinerary
- **Thumbs Up** — likes the idea generally; keep it on the board as an option
- **Not This Time** — send a card to a discard bin (still visible, recoverable)
- Cards can be managed by interacting with the UI directly or by asking the agent ("actually, drop the Fuji idea")

**Data model note:** Every card tracks who added it (client vs. agent) and its status. This is foundational for the post-MVP collaborative mood board where travel companions can be invited to contribute.

**What the agent does behind the scenes:**
- Pulls real inventory: hotels (Ratehawk), flights (Duffel), experiences (GetYourGuide, OV public API), trains
- Cross-references availability, pricing, and editorial validation
- Flags seasonal risks or logistical conflicts early
- Feeds the Dossier with new preference signals from every interaction

### Phase 3: The Build — Strategic Friction

Once the mood board has enough signal and the client submits it, the system transitions into itinerary creation. This is where **necessary friction** becomes a feature. Instead of delivering a finished plan instantly, we drip out progress over hours or days — building tension, excitement, and a sense that something bespoke is being crafted for them.

**The drip cadence:**
- **Clarifying questions** — "We found an incredible private vineyard dinner near Bellagio. Do you prefer a late evening or sunset timing?" Questions signal that real humans and local experts are involved.
- **Progress updates** — "Our Italy specialist is reviewing hotel options in the Dolomites for your dates." Even when AI-driven, frame it as expert curation.
- **Teaser cards** — Drop a single stunning card onto the mood board: a photo, a hotel, a hidden-gem restaurant. No full reveal yet — just enough to spark anticipation.
- **Availability alerts** — "The suite at Villa d'Este is available for your dates, but it's the last one. Want us to hold it?" Creates urgency without pressure.

**Client remains active during this phase:**
- Can continue chatting with the agent to adjust preferences, ask questions, or refine the mood board
- Can reprioritize cards (move items between Must Do / Maybe / Not This Time)
- Can add new ideas that came to mind — the mood board stays alive
- Agent adapts the emerging itinerary based on these interactions

**Pacing rules:**
- Never deliver the full itinerary in under 24 hours, even if the system could
- Space drip touchpoints across the build period (e.g., 2–3 per day)
- Each touchpoint should feel personal and considered, not automated
- The final "your itinerary is ready" moment should feel like an event

### Internal Systems

The following components support the client-facing flow above. They are not phases — they run continuously across the entire lifecycle of a trip.

#### The Command Center

The advisor-facing counterpart to the client experience. Function over aesthetics.

**Queue & workload view:**
- All incoming trip requests in a single dashboard, sortable by status, priority, dates, and advisor assignment
- Each request shows: client name, Dossier summary, mood board snapshot, current phase, and assigned AI agent(s)
- Status pipeline: New → Dreaming → Building → Review → Presented → Booking → Complete

**AI-assisted itinerary assembly:**
- AI agents work autonomously to assemble draft itineraries from mood board signals + inventory APIs
- Advisors interact with agents via **chat / MCP** to make adjustments: *"Move that tour to later in the day to give them time to get to the restaurant"*, *"Swap the hotel — they hate modern architecture"*
- Basic **timeline UI** for arranging itinerary cards — move, reorder, swap. Functional, not fancy. Chat/MCP remains the primary power-user interaction.
- Agents flag issues: scheduling overlaps, unrealistic transit times, sold-out inventory, weather risks

**Client interaction from Command Center:**
- Advisors can send clarifying questions to the client (delivered as drip touchpoints in Phase 3)
- Advisors can update the Dossier directly with new insights from conversations
- All client-facing messages are reviewed/approved by the advisor before sending (or auto-sent within approved templates)

**Dossier management:**
- Full editable view of the client's Dossier from the Command Center
- Advisors annotate with qualitative notes AI can't capture ("she mentioned her anniversary is in October")
- Change history tracked so the team can see how preferences evolve

#### Client Vault

Secure storage for sensitive documents required for booking: passport photos, visa copies, loyalty program numbers, dietary/medical notes, emergency contacts.

- **Encrypted upload** — client-side encryption before upload, stored in S3 with server-side encryption (AES-256)
- **Access-controlled** — only the client and their assigned advisor can view vault contents
- **Document types:** Passport, visa, travel insurance, loyalty cards, other
- **Expiry tracking** — flag documents nearing expiration (e.g., passport valid < 6 months)
- **Reusable across trips** — upload once, use for future bookings

---

### Phase 4: Itinerary Presentation

The "your itinerary is ready" moment. This should feel like an event — the payoff of Phase 3's anticipation.

1. Deliver a polished, visual itinerary — mobile-friendly PDF or in-app experience
2. Day-by-day plan with hotel photos, editorial links, maps, and pricing
3. Where the itinerary graph still has unresolved alternatives, present them as options for the client to choose
4. Offer a callback with a real advisor or local contact to walk through the plan

**Client reviews with the agent:**

The client can chat with the AI agent while reviewing the itinerary. The agent has full context on the graph — not just *what* is planned, but *why*. Every node can carry reasoning: advisor notes, constraint explanations, local knowledge.

- **"Why" questions** — *"Why do we leave at 8am?"* → Agent: *"In Rome on a Wednesday, the Vatican opens at 8:30 and the line builds to 2+ hours by 9am. Your advisor Evan also noted that your afternoon cooking class in Trastevere starts at 2pm, so this keeps the day from feeling rushed."*
- **Change requests** — *"Can we push that to 10am?"* → Agent flags the downstream impact (missed Vatican window, tight on the cooking class) and either adjusts the graph or escalates to the advisor if the change cascades.
- **Notes and preferences** — *"We want to grab espresso near the hotel before we leave"* → Agent adds a note or a new node to the graph for the advisor to see.
- **Alternative selection** — Where branches exist, the client can ask the agent to help them decide: *"Which restaurant do you recommend for our anniversary dinner?"* → Agent draws on Dossier + editorial sources to make a personalized recommendation.

All client feedback in this phase flows back to the advisor via the Command Center. The advisor decides whether to accept changes directly or follow up.

### Phase 5: Booking & Payment

Booking is not a single moment — it's a process. Inventory can fail, prices can shift, and the itinerary graph may need to adapt.

1. Client reviews and approves the final plan (all alternatives resolved)
2. Deposit collected (X% of total) to lock in commitment
3. Advisors begin booking inventory — manually for MVP, working through the itinerary graph node by node

**When bookings fail:**

Hotels get overbooked. Flights change. A rate expires between presentation and booking. This is expected, not exceptional. The system handles it the same way it handles every other itinerary change:

- Advisor updates the affected node's status in the graph (e.g., `approved` → back to `proposed`)
- AI agent suggests alternatives — new hotels, adjusted timing, rerouted transit — using the same graph-aware logic from earlier phases
- If the change is minor (same hotel, different room type), the advisor resolves it directly
- If the change impacts the client's experience (different hotel, different city timing), the client is notified via the same channels used in Phase 3–4 — the agent explains what happened and presents options
- Client can chat with the agent to evaluate alternatives, just like in Phase 4

All confirmations are entered back into the itinerary graph as they succeed. Each node progresses: `approved` → `booked` → `confirmed`. The client can see booking status in real time.

4. Remainder due Y days before departure, collected via Braintree
5. Final confirmation and travel documents delivered — generated from the fully confirmed graph

---

## 5. MVP Scope

### In Scope (MVP)
| Area | Details |
|------|---------|
| **Landing page** | Invitation-only entry, minimal design, contact preference selection |
| **Dossier v1** | Automated client research (public info) + structured intake questionnaire |
| **Mood board + chat** | Split-pane UI: AI chat on one side, visual mood board on the other. Cards (photos, maps, notes) appear as client and agent discuss. Cards can be pinned as "Must Do", kept as "Maybe", or discarded. |
| **Itinerary generation** | AI builds itinerary from client request + Dossier, validated with real inventory |
| **Hotel search** | Ratehawk API integration for availability and rates |
| **Flight search** | Duffel API integration for flights |
| **Itinerary presentation** | Mobile-friendly PDF with images, links, day-by-day plan |
| **Payment** | Braintree integration — deposit + final payment. Client can view invoices and payment history. |
| **Advisor team model** | Multi-advisor teams collaborate on a trip via Command Center. Humans in the loop at every stage. |
| **Command Center v1** | Internal dashboard: request queue, basic timeline UI for arranging itinerary cards, chat/MCP agent interaction, Dossier editing, client messaging |
| **Client vault** | Encrypted document upload (passports, visas, etc.) with access controls and expiry tracking |
| **WhatsApp integration** | Clients can interact via WhatsApp in addition to in-app chat |

### Out of Scope (Post-MVP)
| Area | Details |
|------|---------|
| **Native mobile app** | MVP is web-only (responsive); React Native app comes later |
| **Printed personalized magazine** | Physical mail piece based on Dossier preferences |
| **Multi-traveler Dossiers** | Deep profiles for each member of a group (v1 focuses on primary client) |
| **Experience booking** | GetYourGuide and other experience APIs (v1 presents options but books manually) |
| **Train booking** | Present train options but book manually for MVP |
| **Hotel direct-rate comparison** | Cross-referencing Ratehawk vs. hotel direct websites |
| **AI phone calls to hotels** | Automated voice calls for availability/negotiation |
| **iMessage integration** | iMessage deferred to post-MVP (WhatsApp is in MVP) |
| **Collaborative mood board** | Invite travel companions to add/vote on cards; multi-user presence and attribution |
| **Command Center visual UI** | Polished drag-and-drop itinerary builder, calendar view, advanced analytics, conflict auto-resolution (MVP has functional but minimal timeline) |

---

## 6. Tech Stack

| Layer | Technology |
|-------|-----------|
| **AI** | AWS Bedrock (Claude / other foundation models) |
| **Frontend** | Next.js (responsive web for MVP) |
| **Mobile** | React Native (post-MVP) |
| **Backend** | Next.js API routes on Vercel |
| **Database** | Supabase (Postgres) |
| **Auth** | Supabase Auth (invitation-code gated) |
| **Payments** | Braintree (existing account) |
| **File Storage** | AWS S3 |
| **Hosting** | Vercel |
| **Hotel Inventory** | Ratehawk API |
| **Flight Inventory** | Duffel API |
| **OV Inventory** | OutdoorVoyage.com public API |
| **UI** | Tailwind CSS, Radix UI or similar |

---

## 7. Key Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| **API reliability** (Ratehawk rate-change errors, availability ghosts) | Booking failures, client frustration | Implement retry logic, hold-before-charge pattern; **advisors manually book as fallback** |
| **Seasonal availability** (e.g., August in Italy, event conflicts) | Can't fulfill the itinerary as presented | AI flags high-risk dates; **advisors verify availability directly** before presenting to client |
| **Trust gap** — AI-generated content feels impersonal | Client doesn't convert | Human advisors are genuinely in the loop — not theater. They review, adjust, and personally approve every itinerary |
| **AI quality gaps** — agent produces a weak or unrealistic itinerary | Client loses confidence | **Advisors catch and fix before anything reaches the client.** AI does the heavy lifting; humans do QA. Invest in better AI later. |
| **Scope creep on Dossier** | Over-invest in research before validating the model | V1: structured intake + basic web research. **Advisors fill gaps manually** from conversation. Deepen automation iteratively |
| **Privacy / OSINT ethics** | Clients uncomfortable with depth of research | Transparent about what info is used; let clients review and correct their profile |
| **Booking automation complexity** | Multi-supplier orchestration is hard to automate reliably | **MVP: advisors handle bookings manually** using AI-assembled details. Automate supplier-by-supplier as reliability is proven |

**MVP philosophy:** Human advisors are the safety net. Anywhere the AI or automation isn't ready, an advisor handles it manually. This lets us ship faster and defer engineering complexity to post-MVP — the client experience stays premium regardless because a real person is always backstopping the system.

---

## 8. Success Metrics (MVP)

- **Conversion:** % of invited clients who complete a booking
- **Trip value:** Average booking revenue per client
- **Time to itinerary:** Hours from request to first itinerary draft
- **Client satisfaction:** Post-trip NPS score
- **Rebooking rate:** % of clients who book a second trip within 12 months

---

## 9. Decisions

1. **Chat vs. messaging:** Both. MVP ships with in-app chat AND WhatsApp integration. Meet clients where they are.
2. **Advisor model:** Mix. A team of advisors (OV staff, contracted specialists, local contacts) may collaborate on a single trip. The Command Center supports multi-advisor assignment.
3. **Invitation mechanism:** Personal invite from the CEO. No self-serve signup. Scale the invite list manually for now.
4. **Dossier consent:** Implicit. We use publicly available information without explicit opt-in. Clients can review and correct their profile at any time.
5. **Deposit structure:** Deposit of X% at commitment, remainder due Y days before departure. Exact percentages and timing TBD.
6. **Multi-supplier booking:** Humans handle it. Advisors book manually using the details assembled by AI. The key requirement is that everything gets entered back into the **Itinerary data structure** so it remains the single source of truth.

---

## 10. The Itinerary Graph

The itinerary is the **central data model** of the entire system — the single source of truth for every party. The same underlying data is rendered differently for each audience:

- **Client** sees a polished, visual experience (mood board → PDF → in-app itinerary)
- **Advisor** sees a functional planning view (timeline, cards, logistics, costs)
- **AI agents** read/write structured data (via MCP/API)
- **Booking systems** consume confirmed line items for fulfillment

### Structure

The itinerary is a **graph of items connected by edges**. It evolves from a loose cloud of unconnected nodes (mood board) into a fully resolved, linear path (final booked itinerary).

```
Itinerary
├── Metadata (client, dates, status, assigned advisors, version)
│
├── Nodes (Items)
│   ├── type: destination | flight | hotel | experience | meal | transit | free-time | note
│   ├── status: idea → proposed → approved → booked → confirmed
│   ├── time: start, end, flexible (bool), time-of-day preference
│   ├── location: geo, address, map pin
│   ├── content: title, description, photos, editorial links
│   ├── booking: supplier, confirmation #, cost, payment status
│   ├── source: who added it (client | agent | advisor), when
│   ├── priority: must-do | preferred | optional
│   └── subgraph: optional nested graph (own nodes + edges) for self-contained experiences
│
├── Edges (Relationships between items)
│   ├── follows        → A happens before B (temporal ordering)
│   ├── alternative_to → A or B — pick one (or more). Forms a cluster of options.
│   ├── connected_by   → A is linked to B via a transit node (the edge points through a transit item)
│   ├── requires       → B depends on A (e.g., must be in Milan to do the Milan tour)
│   ├── grouped_with   → A and B belong to the same day/location/theme (loose association)
│   └── each edge has: source (who created it), created_at, confidence (estimated | confirmed)
│
└── Constraints[]
    ├── type: weather | hours | reservation-required | visa | health | event-conflict
    ├── applies-to: node or date range
    └── severity: blocker | warning | info
```

**Transit is a node, not just an edge.** The Bernina Express is both a connection between Tirano and St. Moritz AND a highlight experience. It's modeled as an Item node of type `transit` with `connected_by` edges linking it to the items before and after. A 20-minute taxi ride is also a transit node — just one with less content. This keeps the model uniform.

**Alternatives are edge relationships, not containers.** Instead of a separate `Branches[]` array with pre-defined branch points, alternatives are just items linked by `alternative_to` edges. Three restaurant options for dinner on day 3? Three nodes, each connected to each other by `alternative_to` edges, forming an implicit cluster. Resolution = one gets promoted to `approved`, the others get demoted or removed. This is more flexible:
- Alternatives can exist at any granularity (hotels, restaurants, entire day plans, routes)
- An alternative can itself have sub-items with their own edges
- You can express conditional relationships: "if we pick hotel A, then restaurant X makes sense because it's nearby" (via a `requires` edge from X to A)

**Subgraphs for self-contained experiences.** Some itinerary items are atomic from a scheduling perspective but have rich internal structure. A guided Amalfi Coast tour is a single block on the day's timeline, but inside it there's a boat ride, a stop in Positano, a hike along the Path of the Gods, lunch at a cliffside restaurant, and a return ferry. A node can contain a **subgraph** — its own set of nodes and edges — that tells the full story without cluttering the top-level itinerary.

- The parent node owns the time slot and booking. The subgraph owns the narrative.
- The client sees the subgraph as an expandable detail view: collapse it and it's "Amalfi Coast Tour, 8am–5pm"; expand it and they see every stop, photo, and waypoint.
- Subgraphs can come pre-built from tour operators or OV's own inventory — a reusable template that gets dropped into any itinerary.
- Advisors and AI agents can edit inside the subgraph independently of the parent itinerary (e.g., swap the lunch spot, adjust a waypoint).
- Subgraphs use the same node/edge model as the top-level graph. It's graphs all the way down — though in practice, one level of nesting is usually sufficient.

### How the graph evolves

| Phase | Graph state |
|-------|-------------|
| **Mood board** | Loose nodes, few or no edges. Just a collection of ideas. Maybe some `grouped_with` edges ("these are all Como ideas"). |
| **Planning** | `follows` edges start forming a sequence. `alternative_to` clusters emerge. Transit nodes appear between locations. `requires` edges catch dependencies. |
| **Review** | A primary path is traceable through the graph. Unresolved `alternative_to` clusters are flagged for client decision. Constraints validated against the path. |
| **Finalized** | The graph resolves to a linear DAG — one clear path from start to finish. All alternatives resolved. All transit confirmed. All bookings attached. |

### Key properties

- **Progressive structure:** The graph doesn't demand linearity upfront. A mood board is valid with zero edges. Structure is added incrementally as the plan takes shape — by AI agents, advisors, or the client dragging cards into sequence.
- **Transit as first-class nodes:** Getting from A to B is part of the experience, not an afterthought. Transit nodes carry mode, duration, route, cost — and can themselves be bookable and beautiful (scenic train rides, ferry crossings, private transfers).
- **Progressive detail:** A node starts as just a title and photo ("Lake Como") and accumulates detail over time — specific hotel, room type, check-in time, confirmation number. The data model supports every stage of fidelity.
- **Parallel paths:** Two people in the group doing different things at the same time? Two nodes at the same time slot, no `follows` edge between them. The graph handles it naturally.
- **Append-only history:** Every change is versioned. The advisor moved dinner from 7pm to 8pm? Logged. The client removed a museum visit? Logged. This feeds the Dossier and protects against disputes.

### Why this matters

Without this structure, the itinerary lives in PDFs, WhatsApp messages, Google Docs, and people's heads. The data structure makes the itinerary **programmable** — AI agents can reason about it, advisors can manipulate it, and the client always sees the latest version beautifully rendered. It's also what makes automation possible post-MVP: you can't automate booking if you don't have structured, machine-readable itinerary items.
