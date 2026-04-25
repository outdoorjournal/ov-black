"use client";

import { DriveGlance, DriveZoom, WalkGlance } from "./DriveWalkCard";
import { ExperienceGlance, ExperienceZoom } from "./ExperienceCard";
import { FlightGlance, FlightZoom } from "./FlightCard";
import {
  FreeTimeGlance,
  FreeTimeZoom,
  NoteGlance,
  NoteZoom,
  WaitingGlance,
  WaitingZoom,
} from "./FreeWaitNoteCard";
import { HotelGlance, HotelZoom } from "./HotelCard";
import { MealGlance, MealZoom } from "./MealCard";
import {
  A11yPanel,
  Row,
  Section,
  StatusLegend,
  TaxonomyGrid,
} from "./Sections";
import { StatusShowcase } from "./StatusShowcase";
import { SubwayGlance, SubwayZoom } from "./SubwayCard";
import { TrainGlance, TrainZoom } from "./TrainCard";

export function Shell() {
  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-6xl px-6 py-12 sm:px-10 sm:py-16">
        <Header />

        <Section
          index="01"
          title="Type taxonomy"
          blurb="Every card carries a type token — icon, accent color, three-letter mnemonic, soft tint. The mnemonic appears in the diagram-only views; users see the icon and label."
          notes={[
            "Accents tested ≥ 4.5:1 against #f7f4ee paper for text and ≥ 3:1 for non-text marks.",
            "Hue families are grouped: blues for movement, greens for rest, ambers for activity, terracotta for food. Color helps but never alone.",
            "The mnemonic (FLT, SUB, …) is for advisor tooling and graph debug only.",
          ]}
        >
          <TaxonomyGrid />
        </Section>

        <Section
          index="02"
          title="Status states"
          blurb="One card across its lifecycle. Each status pairs color with a non-color cue so it reads identically to color-blind users."
          notes={[
            "Idea → dashed border, italic title, ~70% opacity.",
            "Approved/Booked/Confirmed escalate from a check, to a lock, to a double-border.",
            "Discarded is grayscale but kept on the page so it can be restored.",
          ]}
        >
          <StatusLegend />
          <StatusShowcase />
        </Section>

        <Section
          index="03"
          title="Flight"
          blurb="Glance: corridor codes + arc + duration. Zoom: time-zone delta, gate/terminal, lounge, jet-lag protocol, scenic side."
          notes={[
            "Time-zone delta is shown explicitly (+13h) — long-haul travelers ask for this constantly.",
            "Right-side / left-side scenery for sunset over the Aleutians, Mt. Fuji, etc. is high-value and rarely surfaced.",
            "Lounge location near gate (vs. far) is more useful than just listing access.",
          ]}
        >
          <Row label="Glance variants">
            <FlightGlance status="proposed" />
            <FlightGlance status="approved" />
            <FlightGlance status="confirmed" />
          </Row>
          <Row label="Zoom">
            <FlightZoom />
          </Row>
        </Section>

        <Section
          index="04"
          title="Subway"
          blurb="Yes — for a real subway leg we draw the actual line in its official color, mark transfer dots in the connecting line's color, and show the signage you'll see at platform level."
          notes={[
            "Tokyo Metro line colors are official; doing the same in NYC, Paris, London preserves wayfinding intuition.",
            "Transfer indicator: a small colored dot above the station for each connecting line.",
            "Signage block uses the actual station signs — JP/local + romanization + English gloss.",
            "Step-free notes (elevators) double as wayfinding for travelers with luggage.",
          ]}
        >
          <Row label="Glance variants">
            <SubwayGlance status="proposed" />
            <SubwayGlance status="approved" />
          </Row>
          <Row label="Zoom — line diagram + signage">
            <SubwayZoom />
          </Row>
        </Section>

        <Section
          index="05"
          title="Train · Shinkansen"
          blurb="Stop sequence as horizontal beads with arrival/departure times. Window briefing flags scenery — Mt. Fuji, Lake Biwa — at the right minute on the right side."
          notes={[
            "Scenery callouts are this card's signature: turn a transit leg into an experience.",
            "JR Pass eligibility is loud and explicit — Hikari/Sakura yes, Nozomi no.",
            "Platform · Car · Seat collapsed into one detail row.",
          ]}
        >
          <Row label="Glance variants">
            <TrainGlance status="proposed" />
            <TrainGlance status="approved" />
          </Row>
          <Row label="Zoom — stop sequence + window briefing">
            <TrainZoom />
          </Row>
        </Section>

        <Section
          index="06"
          title="Private car · driver"
          blurb="Zoom shows the driver (photo, languages, contact), the vehicle (make, plate, capacity), a route preview, and where the meet/greet will happen."
          notes={[
            "Driver continuity for return legs builds trust — surface their previous trips.",
            "Plate format follows local conventions (品川 330 · ぬ 12-34 in Tokyo) — use real glyphs.",
            "Route preview is stylized, not satellite — keeps card calm.",
          ]}
        >
          <Row label="Glance">
            <DriveGlance />
            <WalkGlance />
          </Row>
          <Row label="Zoom — driver + vehicle + route">
            <DriveZoom />
          </Row>
        </Section>

        <Section
          index="07"
          title="Hotel"
          blurb="Glance is image + name + nights. Zoom adds neighborhood blurb, walking distances to upcoming itinerary nodes, and the personal preferences honored."
          notes={[
            "“Walk from your door” to the next 3 itinerary nodes connects the hotel to the day around it.",
            "Preferences (quiet floor, vegetarian breakfast) carry between trips and surface here, not in conversation.",
            "Image has graceful fallback to a colored gradient with a “photo” mark.",
          ]}
        >
          <Row label="Glance variants">
            <HotelGlance status="proposed" />
            <HotelGlance status="booked" />
            <HotelGlance status="confirmed" />
          </Row>
          <Row label="Zoom — neighborhood + walking distances">
            <HotelZoom />
          </Row>
        </Section>

        <Section
          index="08"
          title="Experience"
          blurb="Glance: thumbnail + chips + energy meter. Zoom: hero image, narrative, energy/difficulty arc, best-window strip, gear list, weather contingency."
          notes={[
            "Energy meter is an at-a-glance accessibility win — pairs label with discrete cells.",
            "Best window is a 24-hour strip with the recommended slot highlighted; reads on a small screen.",
            "Allergen / dietary / age flags live as chips with both color and text.",
          ]}
        >
          <Row label="Glance variants">
            <ExperienceGlance status="proposed" />
            <ExperienceGlance status="approved" />
            <ExperienceGlance status="booked" />
          </Row>
          <Row label="Zoom — narrative + energy + windows">
            <ExperienceZoom />
          </Row>
        </Section>

        <Section
          index="09"
          title="Meal"
          blurb="Zoom shows the dish, the etiquette, the diet on file, and useful pre-meal phrases — so the card is also a brief."
          notes={[
            "Phrases card is a small but loud win — travelers screenshot it on the way to dinner.",
            "Diet on file is sourced from the persistent traveler profile, not entered each trip.",
            "Cancellation policy is shown so travelers know the cost of a change.",
          ]}
        >
          <Row label="Glance variants">
            <MealGlance status="proposed" />
            <MealGlance status="booked" />
          </Row>
          <Row label="Zoom — dish + etiquette + phrases">
            <MealZoom />
          </Row>
        </Section>

        <Section
          index="10"
          title="Free time · Waiting · Note"
          blurb="The three card types that compose around the structured ones. Free-time blocks suggest fills; waiting blocks tell you what to do; notes attach to other cards and thread."
          notes={[
            "Free-time card surfaces sunset/sunrise and the carry-over fatigue from the morning.",
            "Waiting card is the only one with a real-time progress bar — a soft countdown.",
            "Notes use a yellow paper background to read as something the team wrote, not the system said.",
          ]}
        >
          <Row label="Glance variants">
            <FreeTimeGlance status="proposed" />
            <WaitingGlance status="proposed" />
            <NoteGlance status="proposed" />
          </Row>
          <Row label="Zoom — free time">
            <FreeTimeZoom />
          </Row>
          <Row label="Zoom — waiting">
            <WaitingZoom />
          </Row>
          <Row label="Zoom — note (threaded)">
            <NoteZoom />
          </Row>
        </Section>

        <Section
          index="11"
          title="Accessibility"
          blurb="The checklist this prototype is meeting (or aspiring to). Anything that fails today is called out so we can plan."
        >
          <A11yPanel />
        </Section>

        <Footer />
      </div>
    </div>
  );
}

function Header() {
  return (
    <header className="mb-12 max-w-3xl">
      <p className="text-[10px] uppercase tracking-[0.4em] text-ink/45">
        Prototype · OV Black · cards
      </p>
      <h1 className="mt-2 font-serif text-4xl leading-tight text-ink sm:text-5xl">
        Card prototypes
      </h1>
      <p className="mt-4 text-[14px] leading-relaxed text-ink/75 sm:text-[15px]">
        A design surface for iterating on the unit of itinerary management — the
        card. Each section pairs glance variants with a zoomed detail view and
        notes on what is being tried. Color cues are paired with icons and
        labels so the system reads to color-blind users.
      </p>
      <p className="mt-3 text-[12px] italic leading-relaxed text-ink/60">
        Source notes:{" "}
        <code className="font-mono text-[11px]">
          apps/agent/src/agent/ai/Itinerary_Planning_System.md
        </code>{" "}
        — the original notebook on travel graphs, cards, and timelines.
      </p>
    </header>
  );
}

function Footer() {
  return (
    <footer className="mt-16 border-t border-ink/10 pt-6 text-[11px] text-ink/55">
      <p>
        Iteration cues: tell the agent which section to expand, what to
        rearrange, or which detail to add — the cards are intentionally cheap
        to redraw.
      </p>
    </footer>
  );
}
