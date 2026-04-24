import type { SampleTimeline } from "../_lib/types";
import { makeEdge, makeItinerary, makeNode, resetCounters } from "./builders";

export function buildTokyoKyoto(): SampleTimeline {
  resetCounters();
  const itinId = "it-tokyo-kyoto";
  const itinerary = makeItinerary(itinId, "Tokyo → Kyoto");

  const inbound = makeNode(itinId, {
    type: "flight",
    title: "LAX → HND",
    meta: {
      day_index: 1,
      rank: 0,
      iata_from: "LAX",
      iata_to: "HND",
      flight_code: "JL 015",
    },
  });
  const aman = makeNode(itinId, {
    type: "hotel",
    title: "Aman Tokyo",
    meta: {
      day_index: 1,
      rank: 1,
      nights: 4,
      snapshot: {
        title: "Aman Tokyo",
        cover_image:
          "https://images.unsplash.com/photo-1540541338287-41700207dee6?q=80&w=1200",
        price: "$2,400 / night",
        location: "Otemachi",
        activities: ["Suite with city view", "Onsen"],
      },
    },
  });

  const sushiSaito = makeNode(itinId, {
    type: "meal",
    title: "Sushi Saito omakase",
    meta: {
      day_index: 2,
      rank: 0,
      time_of_day: "lunch",
      snapshot: { title: "Saito", price: "$520 pp", location: "Akasaka" },
    },
  });
  const teamLab = makeNode(itinId, {
    type: "experience",
    title: "teamLab Borderless private slot",
    meta: {
      day_index: 2,
      rank: 1,
      snapshot: {
        title: "teamLab Borderless",
        cover_image:
          "https://images.unsplash.com/photo-1528109966604-5a6a4a964e8d?q=80&w=1200",
        price: "$320 pp",
        location: "Azabudai",
        activities: ["Private session", "Forest Room"],
      },
    },
  });
  const narukiyo = makeNode(itinId, {
    type: "meal",
    title: "Narukiyo izakaya",
    meta: {
      day_index: 2,
      rank: 2,
      time_of_day: "evening",
      snapshot: { title: "Narukiyo", price: "$180 pp", location: "Shibuya" },
    },
  });

  const tsukiji = makeNode(itinId, {
    type: "experience",
    title: "Tsukiji outer market walk",
    meta: {
      day_index: 3,
      rank: 0,
      snapshot: {
        title: "Tsukiji",
        price: "$220 pp",
        location: "Tokyo",
        activities: ["Knife shop", "Tamago stand", "Tea masters"],
      },
    },
  });
  const golden = makeNode(itinId, {
    type: "experience",
    title: "Golden Gai evening crawl",
    meta: {
      day_index: 3,
      rank: 1,
      snapshot: {
        title: "Golden Gai",
        price: "$160 pp",
        location: "Shinjuku",
      },
    },
  });

  const freeTokyo = makeNode(itinId, {
    type: "free_time",
    title: "Open morning",
    meta: { day_index: 4, rank: 0, body: "Sleep, spa, Ginza browse." },
  });
  const parkHyatt = makeNode(itinId, {
    type: "experience",
    title: "New York Bar sunset",
    meta: {
      day_index: 4,
      rank: 1,
      snapshot: {
        title: "NY Bar · Park Hyatt",
        price: "$90 pp",
        location: "Shinjuku",
      },
    },
  });

  const shinkansen = makeNode(itinId, {
    type: "transit",
    title: "Nozomi Shinkansen · Tokyo → Kyoto",
    meta: {
      day_index: 5,
      rank: 0,
      mode: "Green car",
      snapshot: {
        title: "Shinkansen",
        duration_days: 1,
        location: "2h 15m",
      },
    },
  });
  const tawaraya = makeNode(itinId, {
    type: "hotel",
    title: "Tawaraya Ryokan",
    meta: {
      day_index: 5,
      rank: 1,
      nights: 3,
      snapshot: {
        title: "Tawaraya",
        cover_image:
          "https://images.unsplash.com/photo-1542640244-7e672d6cef4e?q=80&w=1200",
        price: "$1,800 / night",
        location: "Kyoto",
        activities: ["Kaiseki dinner", "Morning tea"],
      },
    },
  });
  const kyoNote = makeNode(itinId, {
    type: "note",
    title: "Pack minimally — ryokan kimono provided",
    meta: {
      day_index: 5,
      rank: 2,
      body: "Tawaraya provides kimono and slippers; formal shoes not needed indoors.",
    },
  });

  const fushimi = makeNode(itinId, {
    type: "experience",
    title: "Fushimi Inari at dawn",
    meta: {
      day_index: 6,
      rank: 0,
      snapshot: {
        title: "Fushimi Inari",
        cover_image:
          "https://images.unsplash.com/photo-1528360983277-13d401cdc186?q=80&w=1200",
        price: "$0",
        location: "Kyoto",
      },
    },
  });
  const tea = makeNode(itinId, {
    type: "experience",
    title: "Tea ceremony with En",
    meta: {
      day_index: 6,
      rank: 1,
      snapshot: {
        title: "Tea ceremony",
        price: "$240 pp",
        location: "Gion",
      },
    },
  });

  const kyoMeal = makeNode(itinId, {
    type: "meal",
    title: "Kikunoi — kaiseki cena",
    meta: {
      day_index: 7,
      rank: 0,
      time_of_day: "evening",
      snapshot: { title: "Kikunoi", price: "$380 pp", location: "Kyoto" },
    },
  });

  const kixOut = makeNode(itinId, {
    type: "flight",
    title: "KIX → LAX",
    meta: {
      day_index: 8,
      rank: 0,
      iata_from: "KIX",
      iata_to: "LAX",
      flight_code: "JL 062",
    },
  });

  const nodes = [
    inbound,
    aman,
    sushiSaito,
    teamLab,
    narukiyo,
    tsukiji,
    golden,
    freeTokyo,
    parkHyatt,
    shinkansen,
    tawaraya,
    kyoNote,
    fushimi,
    tea,
    kyoMeal,
    kixOut,
  ];

  const follow = (a: { id: string }, b: { id: string }) =>
    makeEdge(itinId, a.id, b.id, "follows");

  const edges = [
    follow(inbound, aman),
    follow(aman, sushiSaito),
    follow(sushiSaito, teamLab),
    follow(teamLab, narukiyo),
    follow(narukiyo, tsukiji),
    follow(tsukiji, golden),
    follow(golden, freeTokyo),
    follow(freeTokyo, parkHyatt),
    makeEdge(itinId, parkHyatt.id, shinkansen.id, "connected_by"),
    follow(shinkansen, tawaraya),
    follow(tawaraya, fushimi),
    follow(fushimi, tea),
    follow(tea, kyoMeal),
    follow(kyoMeal, kixOut),
  ];

  return {
    id: "tokyo-kyoto",
    label: "Tokyo → Kyoto",
    subtitle: "Aman, teamLab, ryokan nights · 8 days",
    mood: "onyx",
    dayLabels: [
      "Day 1 · Arrive Tokyo",
      "Day 2 · Tokyo",
      "Day 3 · Tokyo",
      "Day 4 · Tokyo open day",
      "Day 5 · Shinkansen",
      "Day 6 · Kyoto",
      "Day 7 · Kyoto",
      "Day 8 · Depart",
    ],
    itinerary,
    nodes,
    edges,
  };
}
