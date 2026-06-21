import type { SampleTimeline } from "@/app/_components/itinerary-graph/model/baseTypes";
import { makeEdge, makeItinerary, makeNode, resetCounters } from "./builders";

export function buildPatagonia(): SampleTimeline {
  resetCounters();
  const itinId = "it-patagonia";
  const itinerary = makeItinerary(itinId, "Patagonia Trek");

  const inbound = makeNode(itinId, {
    type: "flight",
    title: "JFK → SCL",
    meta: {
      day_index: 1,
      rank: 0,
      iata_from: "JFK",
      iata_to: "SCL",
      flight_code: "LA 533",
    },
  });
  const sclDest = makeNode(itinId, {
    type: "destination",
    title: "Santiago overnight",
    meta: {
      day_index: 1,
      rank: 1,
      snapshot: {
        title: "Santiago",
        cover_image:
          "https://images.unsplash.com/photo-1502175353174-a7a1c2f70f7a?q=80&w=1200",
        location: "Chile",
      },
    },
  });
  const sclHotel = makeNode(itinId, {
    type: "hotel",
    title: "The Singular Santiago",
    meta: {
      day_index: 1,
      rank: 2,
      nights: 1,
      snapshot: {
        title: "The Singular Santiago",
        price: "$820 / night",
        location: "Lastarria",
      },
    },
  });

  const natalesFlight = makeNode(itinId, {
    type: "flight",
    title: "SCL → PNT",
    meta: {
      day_index: 2,
      rank: 0,
      iata_from: "SCL",
      iata_to: "PNT",
      flight_code: "SKY 172",
    },
  });
  const natalesHotel = makeNode(itinId, {
    type: "hotel",
    title: "Tierra Patagonia",
    meta: {
      day_index: 2,
      rank: 1,
      nights: 2,
      snapshot: {
        title: "Tierra Patagonia",
        cover_image:
          "https://images.unsplash.com/photo-1496715976403-7e36dc43f17b?q=80&w=1200",
        price: "$2,100 / night",
        location: "Puerto Natales",
        activities: ["Lake view suite", "Sarmiento spa", "Stargazing"],
      },
    },
  });
  const natalesDinner = makeNode(itinId, {
    type: "meal",
    title: "Restobar Afrigonia",
    meta: {
      day_index: 2,
      rank: 2,
      time_of_day: "evening",
      snapshot: { title: "Afrigonia", price: "$120 pp", location: "Natales" },
    },
  });

  // Days 3-6 — W-circuit parent + nested subgraph
  const wCircuit = makeNode(itinId, {
    type: "experience",
    title: "Torres del Paine — 4-day W Circuit",
    meta: {
      day_index: 3,
      rank: 0,
      snapshot: {
        title: "W Circuit",
        cover_image:
          "https://images.unsplash.com/photo-1531065208531-4036c0dba3ca?q=80&w=1200",
        price: "$4,800 pp",
        duration_days: 4,
        difficulty: "Challenging",
        location: "Torres del Paine NP",
        activities: [
          "Grey Glacier",
          "French Valley",
          "Base of the Towers sunrise",
        ],
      },
    },
  });
  const parent = wCircuit.id;
  const wDay1 = makeNode(itinId, {
    type: "experience",
    title: "Grey Glacier hike",
    parent_subgraph_id: parent,
    meta: {
      snapshot: { title: "Grey Glacier", duration_days: 1 },
    },
  });
  const wRef1 = makeNode(itinId, {
    type: "hotel",
    title: "Refugio Paine Grande",
    parent_subgraph_id: parent,
    meta: { nights: 1, snapshot: { title: "Paine Grande refugio" } },
  });
  const wDay2 = makeNode(itinId, {
    type: "experience",
    title: "French Valley",
    parent_subgraph_id: parent,
    meta: { snapshot: { title: "French Valley", duration_days: 1 } },
  });
  const wRef2 = makeNode(itinId, {
    type: "hotel",
    title: "Refugio Los Cuernos",
    parent_subgraph_id: parent,
    meta: { nights: 1, snapshot: { title: "Los Cuernos refugio" } },
  });
  const wDay3 = makeNode(itinId, {
    type: "experience",
    title: "Base of the Towers sunrise",
    parent_subgraph_id: parent,
    meta: { snapshot: { title: "Towers sunrise", duration_days: 1 } },
  });
  const wRef3 = makeNode(itinId, {
    type: "hotel",
    title: "Refugio Chileno",
    parent_subgraph_id: parent,
    meta: { nights: 1, snapshot: { title: "Chileno refugio" } },
  });
  const wOut = makeNode(itinId, {
    type: "transit",
    title: "Van back to Natales",
    parent_subgraph_id: parent,
    meta: { mode: "Private van" },
  });

  const calafateTransit = makeNode(itinId, {
    type: "transit",
    title: "Overland to El Calafate",
    meta: { day_index: 7, rank: 0, mode: "Private vehicle" },
  });
  const calHotel = makeNode(itinId, {
    type: "hotel",
    title: "EOLO Patagonia",
    meta: {
      day_index: 7,
      rank: 1,
      nights: 2,
      snapshot: {
        title: "EOLO Patagonia",
        price: "$1,700 / night",
        location: "El Calafate",
      },
    },
  });
  const perito = makeNode(itinId, {
    type: "experience",
    title: "Perito Moreno mini-trek",
    meta: {
      day_index: 8,
      rank: 0,
      snapshot: {
        title: "Perito Moreno",
        cover_image:
          "https://images.unsplash.com/photo-1504281623087-1a6b36b3f45a?q=80&w=1200",
        price: "$520 pp",
        duration_days: 1,
        activities: ["Ice crampons", "Whisky on ice"],
      },
    },
  });

  const retHome = makeNode(itinId, {
    type: "flight",
    title: "FTE → SCL → JFK",
    meta: {
      day_index: 10,
      rank: 0,
      iata_from: "FTE",
      iata_to: "JFK",
      flight_code: "LA 8294",
    },
  });

  const nodes = [
    inbound,
    sclDest,
    sclHotel,
    natalesFlight,
    natalesHotel,
    natalesDinner,
    wCircuit,
    wDay1,
    wRef1,
    wDay2,
    wRef2,
    wDay3,
    wRef3,
    wOut,
    calafateTransit,
    calHotel,
    perito,
    retHome,
  ];

  const follow = (a: { id: string }, b: { id: string }) =>
    makeEdge(itinId, a.id, b.id, "follows");

  const edges = [
    follow(inbound, sclDest),
    follow(sclDest, sclHotel),
    follow(sclHotel, natalesFlight),
    follow(natalesFlight, natalesHotel),
    follow(natalesHotel, natalesDinner),
    follow(natalesDinner, wCircuit),
    // nested edges for the W
    follow(wDay1, wRef1),
    follow(wRef1, wDay2),
    follow(wDay2, wRef2),
    follow(wRef2, wDay3),
    follow(wDay3, wRef3),
    follow(wRef3, wOut),
    // top-level continues
    follow(wCircuit, calafateTransit),
    follow(calafateTransit, calHotel),
    follow(calHotel, perito),
    follow(perito, retHome),
  ];

  return {
    id: "patagonia",
    label: "Patagonia Trek",
    subtitle: "Santiago → Paine → Calafate · 10 days",
    mood: "glacial",
    dayLabels: [
      "Day 1 · Santiago",
      "Day 2 · Natales",
      "Day 3–6 · Torres del Paine",
      "",
      "",
      "",
      "Day 7 · Calafate transfer",
      "Day 8 · Perito Moreno",
      "Day 9 · Rest",
      "Day 10 · Depart",
    ],
    itinerary,
    nodes,
    edges,
  };
}
