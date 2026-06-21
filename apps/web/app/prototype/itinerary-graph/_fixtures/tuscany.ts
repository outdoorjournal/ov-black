import type { SampleTimeline } from "@/app/_components/itinerary-graph/model/baseTypes";
import { makeEdge, makeItinerary, makeNode, resetCounters } from "./builders";

export function buildTuscany(): SampleTimeline {
  resetCounters();
  const itinId = "it-tuscany";
  const itinerary = makeItinerary(itinId, "Tuscany Slow Week");

  const arrFlight = makeNode(itinId, {
    type: "flight",
    title: "JFK → FCO",
    meta: {
      day_index: 1,
      rank: 0,
      iata_from: "JFK",
      iata_to: "FCO",
      flight_code: "AZ 611",
      snapshot: {
        title: "Overnight to Rome",
        price: "First · $6,200",
        location: "Alitalia",
      },
    },
  });
  const romeDest = makeNode(itinId, {
    type: "destination",
    title: "Rome",
    meta: {
      day_index: 1,
      rank: 1,
      snapshot: {
        title: "Rome",
        cover_image:
          "https://images.unsplash.com/photo-1531572753322-ad063cecc140?q=80&w=1200",
        location: "Italy",
      },
    },
  });
  const romeHotel = makeNode(itinId, {
    type: "hotel",
    title: "Hotel de Russie",
    meta: {
      day_index: 1,
      rank: 2,
      nights: 2,
      snapshot: {
        title: "Hotel de Russie",
        cover_image:
          "https://images.unsplash.com/photo-1566073771259-6a8506099945?q=80&w=1200",
        price: "$1,200 / night",
        location: "Piazza del Popolo",
        activities: ["Garden suite", "Rooftop dinner"],
      },
    },
  });

  const colosseum = makeNode(itinId, {
    type: "experience",
    title: "Private Colosseum at dusk",
    meta: {
      day_index: 2,
      rank: 0,
      snapshot: {
        title: "Private Colosseum at dusk",
        cover_image:
          "https://images.unsplash.com/photo-1552832230-c0197dd311b5?q=80&w=1200",
        price: "$680 pp",
        duration_days: 1,
        location: "Colosseum",
        activities: ["After-hours access", "Arena floor", "Curator guide"],
      },
    },
  });
  const romeDinner = makeNode(itinId, {
    type: "meal",
    title: "Roscioli — omakase cena",
    meta: {
      day_index: 2,
      rank: 1,
      time_of_day: "evening",
      snapshot: {
        title: "Roscioli",
        price: "$220 pp",
        location: "Campo de' Fiori",
      },
    },
  });

  const transitToChianti = makeNode(itinId, {
    type: "transit",
    title: "Private car → Chianti",
    meta: {
      day_index: 3,
      rank: 0,
      mode: "Mercedes S-Class",
      snapshot: { title: "Private transfer", duration_days: 1 },
    },
  });
  const villa = makeNode(itinId, {
    type: "hotel",
    title: "Castello di Casole",
    meta: {
      day_index: 3,
      rank: 1,
      nights: 3,
      snapshot: {
        title: "Castello di Casole",
        cover_image:
          "https://images.unsplash.com/photo-1544113503-7ad532d0d2a1?q=80&w=1200",
        price: "$2,400 / night",
        location: "Chianti",
        activities: ["Pool suite", "Truffle hunt", "Cellar dinner"],
      },
    },
  });
  const truffle = makeNode(itinId, {
    type: "experience",
    title: "Truffle hunt with Lagotto",
    meta: {
      day_index: 4,
      rank: 0,
      snapshot: {
        title: "Truffle hunt",
        cover_image:
          "https://images.unsplash.com/photo-1447933601403-0c6688de566e?q=80&w=1200",
        price: "$520 pp",
        duration_days: 1,
        location: "Chianti hills",
        activities: ["2-hr forest walk", "Tasting lunch"],
      },
    },
  });

  // Day 5 — the Siena vs San Gimignano choice
  const sienaDay = makeNode(itinId, {
    type: "experience",
    title: "Siena — private Duomo & Palio museum",
    meta: {
      day_index: 5,
      rank: 0,
      snapshot: {
        title: "Siena day",
        cover_image:
          "https://images.unsplash.com/photo-1583922606661-0822ed0bd916?q=80&w=1200",
        price: "$780 pp",
        location: "Siena",
        activities: ["Duomo private tour", "Piazza lunch", "Palio museum"],
      },
    },
  });
  const sanGimDay = makeNode(itinId, {
    type: "experience",
    status: "proposed",
    title: "San Gimignano — medieval towers & enoteca",
    meta: {
      day_index: 5,
      rank: 1,
      snapshot: {
        title: "San Gimignano",
        cover_image:
          "https://images.unsplash.com/photo-1592395600103-3e4b5b1d41dc?q=80&w=1200",
        price: "$690 pp",
        location: "San Gimignano",
        activities: ["Tower climb", "Vernaccia tasting", "Gelato stop"],
      },
    },
  });

  const florenceTransit = makeNode(itinId, {
    type: "transit",
    title: "Car → Florence",
    meta: { day_index: 6, rank: 0, mode: "Private driver" },
  });
  const florenceHotel = makeNode(itinId, {
    type: "hotel",
    title: "Portrait Firenze",
    meta: {
      day_index: 6,
      rank: 1,
      nights: 2,
      snapshot: {
        title: "Portrait Firenze",
        cover_image:
          "https://images.unsplash.com/photo-1467269204594-9661b134dd2b?q=80&w=1200",
        price: "$1,450 / night",
        location: "Ponte Vecchio",
      },
    },
  });
  const uffizi = makeNode(itinId, {
    type: "experience",
    title: "Uffizi after-hours",
    meta: {
      day_index: 6,
      rank: 2,
      snapshot: {
        title: "Uffizi after-hours",
        price: "$1,100 pp",
        location: "Florence",
        activities: ["Private curator", "Botticelli gallery"],
      },
    },
  });

  const outFlight = makeNode(itinId, {
    type: "flight",
    title: "FLR → JFK",
    meta: {
      day_index: 7,
      rank: 0,
      iata_from: "FLR",
      iata_to: "JFK",
      flight_code: "DL 415",
    },
  });

  const nodes = [
    arrFlight,
    romeDest,
    romeHotel,
    colosseum,
    romeDinner,
    transitToChianti,
    villa,
    truffle,
    sienaDay,
    sanGimDay,
    florenceTransit,
    florenceHotel,
    uffizi,
    outFlight,
  ];

  const follow = (
    from: { id: string },
    to: { id: string },
  ) => makeEdge(itinId, from.id, to.id, "follows");

  const edges = [
    follow(arrFlight, romeDest),
    follow(romeDest, romeHotel),
    follow(romeHotel, colosseum),
    follow(colosseum, romeDinner),
    follow(romeDinner, transitToChianti),
    follow(transitToChianti, villa),
    follow(villa, truffle),
    follow(truffle, sienaDay),
    makeEdge(itinId, sanGimDay.id, sienaDay.id, "alternative_to"),
    follow(sienaDay, florenceTransit),
    follow(florenceTransit, florenceHotel),
    follow(florenceHotel, uffizi),
    follow(uffizi, outFlight),
  ];

  return {
    id: "tuscany",
    label: "Tuscany Slow Week",
    subtitle: "Rome → Chianti → Florence · 7 nights",
    mood: "amber",
    dayLabels: [
      "Day 1 · Arrive Rome",
      "Day 2 · Rome",
      "Day 3 · Chianti",
      "Day 4 · Chianti",
      "Day 5 · Choose a day trip",
      "Day 6 · Florence",
      "Day 7 · Depart",
    ],
    itinerary,
    nodes,
    edges,
  };
}
