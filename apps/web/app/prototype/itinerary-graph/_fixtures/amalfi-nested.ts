import type { SampleTimeline } from "@/app/_components/itinerary-graph/model/baseTypes";
import { makeEdge, makeItinerary, makeNode, resetCounters } from "./builders";

export function buildAmalfi(): SampleTimeline {
  resetCounters();
  const itinId = "it-amalfi";
  const itinerary = makeItinerary(itinId, "Amalfi Romance");

  const inbound = makeNode(itinId, {
    type: "flight",
    title: "JFK → FCO",
    meta: {
      day_index: 1,
      rank: 0,
      iata_from: "JFK",
      iata_to: "FCO",
      flight_code: "AZ 611",
    },
  });
  const transfer = makeNode(itinId, {
    type: "transit",
    title: "Helicopter → Positano",
    meta: {
      day_index: 1,
      rank: 1,
      mode: "Helicopter",
      snapshot: { title: "Heli transfer", duration_days: 1 },
    },
  });
  const leSirenuse = makeNode(itinId, {
    type: "hotel",
    title: "Le Sirenuse",
    meta: {
      day_index: 1,
      rank: 2,
      nights: 4,
      snapshot: {
        title: "Le Sirenuse",
        cover_image:
          "https://images.unsplash.com/photo-1533105079780-92b9be482077?q=80&w=1200",
        price: "$1,900 / night",
        location: "Positano",
        activities: ["Sea-view suite", "Champagne bar"],
      },
    },
  });

  const champagneBar = makeNode(itinId, {
    type: "meal",
    title: "Franco's — sunset aperitivo",
    meta: {
      day_index: 2,
      rank: 0,
      time_of_day: "evening",
      snapshot: { title: "Franco's", price: "$120 pp", location: "Positano" },
    },
  });

  // Day 3 — three alternative_to branches
  const capriDay = makeNode(itinId, {
    type: "experience",
    title: "Capri boat & Blue Grotto",
    meta: {
      day_index: 3,
      rank: 0,
      snapshot: {
        title: "Capri boat",
        cover_image:
          "https://images.unsplash.com/photo-1516483638261-f4dbaf036963?q=80&w=1200",
        price: "$2,200 couple",
        location: "Capri",
        activities: ["Private gozzo", "Blue Grotto", "Lunch at La Fontelina"],
      },
    },
  });
  const pompeiiDay = makeNode(itinId, {
    type: "experience",
    status: "proposed",
    title: "Pompeii — private archaeologist",
    meta: {
      day_index: 3,
      rank: 1,
      snapshot: {
        title: "Pompeii",
        cover_image:
          "https://images.unsplash.com/photo-1597432893859-abad0d6f7a1b?q=80&w=1200",
        price: "$1,800 couple",
        location: "Pompeii",
        activities: ["After-hours access", "Villa of Mysteries"],
      },
    },
  });
  const ravelloDay = makeNode(itinId, {
    type: "experience",
    status: "proposed",
    title: "Ravello — gardens & villa drive",
    meta: {
      day_index: 3,
      rank: 2,
      snapshot: {
        title: "Ravello",
        cover_image:
          "https://images.unsplash.com/photo-1528733942180-06f79ccd0f9b?q=80&w=1200",
        price: "$1,400 couple",
        location: "Ravello",
        activities: ["Villa Cimbrone", "Concerto", "Long lunch"],
      },
    },
  });

  const zass = makeNode(itinId, {
    type: "meal",
    title: "La Sponda — candlelit dinner",
    meta: {
      day_index: 3,
      rank: 3,
      time_of_day: "evening",
      snapshot: { title: "La Sponda", price: "$520 couple" },
    },
  });

  const freeDay = makeNode(itinId, {
    type: "free_time",
    title: "Pool & rest",
    meta: {
      day_index: 4,
      rank: 0,
      body: "No obligations. Late breakfast, pool, massage.",
    },
  });

  const outTransit = makeNode(itinId, {
    type: "transit",
    title: "Return to Naples",
    meta: { day_index: 5, rank: 0, mode: "Private car" },
  });
  const outFlight = makeNode(itinId, {
    type: "flight",
    title: "NAP → JFK",
    meta: {
      day_index: 5,
      rank: 1,
      iata_from: "NAP",
      iata_to: "JFK",
      flight_code: "DL 153",
    },
  });

  const nodes = [
    inbound,
    transfer,
    leSirenuse,
    champagneBar,
    capriDay,
    pompeiiDay,
    ravelloDay,
    zass,
    freeDay,
    outTransit,
    outFlight,
  ];

  const follow = (a: { id: string }, b: { id: string }) =>
    makeEdge(itinId, a.id, b.id, "follows");

  const edges = [
    follow(inbound, transfer),
    follow(transfer, leSirenuse),
    follow(leSirenuse, champagneBar),
    follow(champagneBar, capriDay),
    makeEdge(itinId, pompeiiDay.id, capriDay.id, "alternative_to"),
    makeEdge(itinId, ravelloDay.id, capriDay.id, "alternative_to"),
    follow(capriDay, zass),
    follow(zass, freeDay),
    follow(freeDay, outTransit),
    follow(outTransit, outFlight),
  ];

  return {
    id: "amalfi",
    label: "Amalfi Romance",
    subtitle: "Positano base, three day choices · 5 nights",
    mood: "tidal",
    dayLabels: [
      "Day 1 · Arrive",
      "Day 2 · Positano",
      "Day 3 · Choose a day",
      "Day 4 · Rest",
      "Day 5 · Depart",
    ],
    itinerary,
    nodes,
    edges,
  };
}
