// Render proofs for the Google-Places POI enrichment on experience / meal
// cards. The card_mapping layer now emits a `place` block (rating, review
// count, opening hours, website/phone, a keyless map deep link, and a signed
// photo token). These prove the glance tile shows a rating + a proxied photo,
// the zoom sheet surfaces the full block with working links, and the photo-URL
// helper builds the absolute proxy URL from the runtime API base.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import { NodeCard } from "@/app/_components/itinerary-graph/views/horizontal/NodeCard";
import { NodeZoomCard } from "@/app/_components/itinerary-graph/shared/cards/NodeZoomCard";
import { placePhotoUrl } from "@/app/_components/itinerary-graph/model/placePhoto";

const API_BASE = "http://localhost:8000";
const PHOTO_TOKEN = "signed.photo.token";
const MAPS_URL =
  "https://www.google.com/maps/search/?api=1&query=34.9671,135.7727&query_place_id=ChIJ8Rfu99kIAWARRZ5jLrUJ0Hk";

// Mirrors apps/api card_mapping.experience_item_to_card_attrs(...).model_dump()
// for a Google-Places experience (Fushimi Inari): snapshot + a `place` block.
function experienceNode(overrides: Partial<NodeResponse> = {}): NodeResponse {
  return {
    id: "n-exp",
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "approved",
    title: "Fushimi Inari Taisha",
    source: "google_places",
    source_id: "ChIJ8Rfu99kIAWARRZ5jLrUJ0Hk",
    metadata: {
      kind: "experience",
      description: "Thousands of vermilion torii up the mountain.",
      location: { lat: 34.9671, lng: 135.7727, label: "68 Fukakusa, Fushimi Ward, Kyoto" },
      snapshot: { title: "Fushimi Inari Taisha", location: "Fushimi Ward, Kyoto" },
      start_time: "2026-07-12T09:00:00+09:00",
      duration_minutes: 120,
      place: {
        rating: 4.7,
        rating_count: 92134,
        hours: ["Monday: Open 24 hours", "Tuesday: Open 24 hours"],
        website: "https://inari.jp.example/",
        phone: "+81 75-641-7331",
        maps_url: MAPS_URL,
        photo_token: PHOTO_TOKEN,
      },
    },
    ...overrides,
  } as NodeResponse;
}

describe("placePhotoUrl", () => {
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE));
  afterEach(() => vi.unstubAllEnvs());

  test("builds the absolute proxy URL from the API base + token", () => {
    expect(placePhotoUrl(PHOTO_TOKEN)).toBe(
      `${API_BASE}/integrations/google-places/photo?token=${encodeURIComponent(PHOTO_TOKEN)}`,
    );
  });

  test("returns undefined without a token", () => {
    expect(placePhotoUrl(undefined)).toBeUndefined();
  });

  test("returns undefined when no API base is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    vi.stubEnv("OVB_API_BASE_URL", "");
    expect(placePhotoUrl(PHOTO_TOKEN)).toBeUndefined();
  });
});

describe("experience glance tile", () => {
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE));
  afterEach(() => vi.unstubAllEnvs());

  test("shows the crowd rating with a compact review count", () => {
    render(<NodeCard node={experienceNode()} tzOffsetHours={9} />);
    expect(screen.getByText(/★\s*4\.7/)).toBeInTheDocument();
    expect(screen.getByText(/92k/)).toBeInTheDocument();
  });

  test("points the tile photo at the keyed proxy, carrying the signed token", () => {
    const { container } = render(<NodeCard node={experienceNode()} tzOffsetHours={9} />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toContain("/integrations/google-places/photo?token=");
    expect(img?.getAttribute("src")).toContain(encodeURIComponent(PHOTO_TOKEN));
  });
});

describe("experience zoom sheet", () => {
  beforeEach(() => vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE));
  afterEach(() => vi.unstubAllEnvs());

  test("surfaces rating, review count and opening hours", () => {
    render(<NodeZoomCard node={experienceNode()} tzOffsetHours={9} />);
    expect(screen.getByText(/★\s*4\.7/)).toBeInTheDocument();
    expect(screen.getByText(/92,134 reviews/)).toBeInTheDocument();
    expect(screen.getByText("Monday: Open 24 hours")).toBeInTheDocument();
  });

  test("renders working website, phone and Google Maps links", () => {
    render(<NodeZoomCard node={experienceNode()} tzOffsetHours={9} />);

    const maps = screen.getByRole("link", { name: /View on Google Maps/i });
    expect(maps).toHaveAttribute("href", MAPS_URL);
    expect(maps).toHaveAttribute("target", "_blank");

    expect(screen.getByRole("link", { name: /Website/i })).toHaveAttribute(
      "href",
      "https://inari.jp.example/",
    );
    // Phone dials via a tel: link with whitespace stripped.
    expect(screen.getByRole("link", { name: /\+81/ })).toHaveAttribute(
      "href",
      "tel:+8175-641-7331",
    );
  });

  test("omits the place block entirely when a node carries no POI facts", () => {
    const bare = experienceNode({
      metadata: {
        kind: "experience",
        snapshot: { title: "Private ridge hike" },
      },
    });
    render(<NodeZoomCard node={bare} tzOffsetHours={9} />);
    expect(screen.queryByText(/reviews/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Google Maps/i })).not.toBeInTheDocument();
  });
});
