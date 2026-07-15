// The basecamp itinerary tiles must read like the itinerary cards: a hero
// image (or a placeholder gradient), the trip name, and a legible timeframe.
// This locks the cover-resolution priority (Places token → snapshot URL →
// gradient) and the date-range / flexible / to-be-set timeframe copy.

import { render, screen } from "@testing-library/react";
import { beforeAll, expect, test } from "vitest";

import type { MyItinerarySummary } from "@ov-black/api-client";

import { ItineraryGrid } from "@/app/basecamp/_components/ItineraryGrid";

beforeAll(() => {
  // placePhotoUrl needs a configured API base to build the proxy URL.
  process.env["NEXT_PUBLIC_API_BASE_URL"] = "https://api.test";
});

function summary(over: Partial<MyItinerarySummary>): MyItinerarySummary {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    title: "Kyoto in Autumn",
    status: "in_studio",
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-02T00:00:00Z",
    ...over,
  };
}

test("prefers a Places photo token, then a snapshot URL, then a gradient", () => {
  render(
    <ItineraryGrid
      itineraries={[
        summary({
          id: "a",
          title: "Token trip",
          cover_photo_token: "tok-abc",
          cover_image: "https://img/ignored.jpg",
        }),
        summary({ id: "b", title: "URL trip", cover_image: "https://img/direct.jpg" }),
        summary({ id: "c", title: "No image trip" }),
      ]}
    />,
  );

  const tokenCard = screen.getByRole("link", { name: /Token trip/ });
  expect(tokenCard.querySelector("img")).toHaveAttribute(
    "src",
    "https://api.test/integrations/google-places/photo?token=tok-abc",
  );

  const urlCard = screen.getByRole("link", { name: /URL trip/ });
  expect(urlCard.querySelector("img")).toHaveAttribute("src", "https://img/direct.jpg");

  // No cover → no <img>, the gradient placeholder carries the tile.
  const bareCard = screen.getByRole("link", { name: /No image trip/ });
  expect(bareCard.querySelector("img")).toBeNull();
});

test("an explicit hero image wins over the node cover", () => {
  // Campaign trips (e.g. Olympus) carry a hero_image — the tile shows it (matching
  // the dashboard) rather than an arbitrarily-ordered node cover.
  render(
    <ItineraryGrid
      itineraries={[
        summary({
          id: "olympus",
          title: "Olympus trip",
          hero_image: "https://img/olympus-summit.jpg",
          cover_photo_token: "tok-abc",
          cover_image: "https://img/ignored.jpg",
        }),
      ]}
    />,
  );

  const card = screen.getByRole("link", { name: /Olympus trip/ });
  expect(card.querySelector("img")).toHaveAttribute("src", "https://img/olympus-summit.jpg");
});

test("no hero image falls back to the node cover", () => {
  render(
    <ItineraryGrid
      itineraries={[
        summary({ id: "x", title: "Plain trip", cover_image: "https://img/node.jpg" }),
      ]}
    />,
  );

  const card = screen.getByRole("link", { name: /Plain trip/ });
  expect(card.querySelector("img")).toHaveAttribute("src", "https://img/node.jpg");
});

test("renders a same-month date range as a compact span", () => {
  render(
    <ItineraryGrid
      itineraries={[summary({ date_start: "2026-09-01", date_end: "2026-09-08" })]}
    />,
  );
  expect(screen.getByText("September 1–8, 2026")).toBeInTheDocument();
});

test("renders a cross-month date range with both months", () => {
  render(
    <ItineraryGrid
      itineraries={[summary({ date_start: "2026-09-28", date_end: "2026-10-03" })]}
    />,
  );
  expect(screen.getByText("Sep 28 – Oct 3, 2026")).toBeInTheDocument();
});

test("falls back to nights for a flexible trip, then to a gentle prompt", () => {
  render(
    <ItineraryGrid
      itineraries={[
        summary({ id: "flex", title: "Flexible", timing_kind: "flexible", duration_nights: 7 }),
        summary({ id: "blank", title: "Blank" }),
      ]}
    />,
  );
  expect(screen.getByText("7 nights · dates flexible")).toBeInTheDocument();
  expect(screen.getByText("Dates to be set")).toBeInTheDocument();
});

test("labels a solo traveler's open-fork trunk as their working version", () => {
  render(
    <ItineraryGrid
      itineraries={[summary({ status: "in_studio", has_open_fork: true })]}
    />,
  );
  expect(screen.getByText("Your working version")).toBeInTheDocument();
});
