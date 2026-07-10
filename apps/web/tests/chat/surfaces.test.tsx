// The drawer beside the chat: wire parsing, polyline decoding, and the
// interactive pieces that carry contract weight —
//   1. a `surface` SSE frame survives parseFrames and narrows per kind,
//      with malformed payloads dropped rather than opening a broken panel
//   2. decodePolyline reproduces Google's reference vector ([lng, lat] order)
//   3. OptionsSurface: a tap answers with the option (and disables while a
//      turn is streaming — R014's disabled-not-spinner rule)
//   4. PlaceChip inside a SurfaceContext opens the drawer instead of the
//      legacy popover; outside one, the popover fallback still works.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { parseFrames } from "@/lib/agentStream";
import { decodePolyline } from "@/lib/chat/polyline";
import { OptionsSurface } from "@/app/_components/concierge/surfaces/OptionsSurface";
import { PlaceChip } from "@/app/chat/[client_id]/_components/PlaceChip";
import { SurfaceContext } from "@/app/_components/concierge/surfaces/SurfaceContext";
import {
  surfaceFromFrame,
  type ActiveSurface,
} from "@/app/_components/concierge/surfaces/types";
import { formatDistance, formatDuration } from "@/app/_components/concierge/surfaces/RouteSurface";

const ROUTE_FRAME = {
  type: "surface" as const,
  surface_id: "srf-1",
  kind: "route",
  payload: {
    headline: "The mountain road",
    highlights: [{ title: "Odawara castle", detail: "worth a pause" }],
    route: {
      origin: "Tokyo Station",
      destination: "Hakone",
      waypoints: [],
      mode: "drive",
      distance_meters: 96432,
      duration_seconds: 5411,
      encoded_polyline: "abc",
      legs: [
        {
          distance_meters: 96432,
          duration_seconds: 5411,
          start_lat: 35.68,
          start_lng: 139.76,
          end_lat: 35.23,
          end_lng: 139.1,
        },
      ],
    },
  },
};

test("surface frames survive the SSE parser; malformed ones drop", () => {
  const good = `data: ${JSON.stringify(ROUTE_FRAME)}\n\n`;
  const noKind = `data: {"type":"surface","surface_id":"s","payload":{}}\n\n`;
  const { frames } = parseFrames(good + noKind);
  expect(frames).toHaveLength(1);
  expect(frames[0]).toMatchObject({ type: "surface", kind: "route" });
});

test("surfaceFromFrame narrows a route payload and drops unknown kinds", () => {
  const route = surfaceFromFrame(ROUTE_FRAME);
  expect(route).not.toBeNull();
  if (route?.kind !== "route") throw new Error("expected route surface");
  expect(route.route.origin).toBe("Tokyo Station");
  expect(route.route.highlights).toEqual([{ title: "Odawara castle", detail: "worth a pause" }]);
  expect(route.route.legs[0]?.startLng).toBe(139.76);

  expect(
    surfaceFromFrame({ type: "surface", surface_id: "s", kind: "hologram", payload: {} }),
  ).toBeNull();
  expect(
    surfaceFromFrame({ type: "surface", surface_id: "s", kind: "route", payload: {} }),
  ).toBeNull();
});

test("surfaceFromFrame narrows options and requires two usable options", () => {
  const surface = surfaceFromFrame({
    type: "surface",
    surface_id: "srf-2",
    kind: "options",
    payload: {
      question: "A or B?",
      options: [
        { id: "opt-1", title: "A", case: "Quieter." },
        { id: "opt-2", title: "B" },
      ],
    },
  });
  if (surface?.kind !== "options") throw new Error("expected options surface");
  expect(surface.options.options.map((o) => o.title)).toEqual(["A", "B"]);

  expect(
    surfaceFromFrame({
      type: "surface",
      surface_id: "s",
      kind: "options",
      payload: { question: "One?", options: [{ id: "opt-1", title: "Only" }] },
    }),
  ).toBeNull();
});

test("decodePolyline reproduces Google's reference vector as [lng, lat]", () => {
  const coords = decodePolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@");
  expect(coords).toEqual([
    [-120.2, 38.5],
    [-120.95, 40.7],
    [-126.453, 43.252],
  ]);
});

test("route facts format for humans", () => {
  expect(formatDistance(96432)).toBe("96.4 km");
  expect(formatDistance(650)).toBe("650 m");
  expect(formatDuration(5411)).toBe("1 hr 30 min");
  expect(formatDuration(240)).toBe("4 min");
});

test("choosing an option answers with the option; busy disables the buttons", () => {
  const onChoose = vi.fn();
  const view = {
    question: "Which base?",
    options: [
      { id: "opt-1", title: "Ryokan Sasayuri-an", case: "Quietest." },
      { id: "opt-2", title: "Koyasan temple stay" },
    ],
  };
  const { rerender } = render(<OptionsSurface options={view} busy={false} onChoose={onChoose} />);

  const buttons = screen.getAllByTestId("options-surface-choose");
  expect(buttons).toHaveLength(2);
  fireEvent.click(buttons[1]!);
  expect(onChoose).toHaveBeenCalledWith(view.options[1]);

  rerender(<OptionsSurface options={view} busy={true} onChoose={onChoose} />);
  for (const button of screen.getAllByTestId("options-surface-choose")) {
    expect(button).toBeDisabled();
  }
});

test("a place chip opens the drawer inside a SurfaceContext, popover outside", () => {
  const open = vi.fn<(s: ActiveSurface) => void>();
  render(
    <SurfaceContext.Provider value={{ open }}>
      <PlaceChip label="Fiskardo" query="Fiskardo" />
    </SurfaceContext.Provider>,
  );
  fireEvent.click(screen.getByTestId("place-chip"));
  expect(open).toHaveBeenCalledWith({ kind: "place", label: "Fiskardo", query: "Fiskardo" });
  expect(screen.queryByTestId("place-chip-map")).toBeNull();
});

test("a place chip without a SurfaceContext keeps the legacy popover", () => {
  render(<PlaceChip label="Fiskardo" query="Fiskardo" />);
  fireEvent.click(screen.getByTestId("place-chip"));
  expect(screen.getByTestId("place-chip-map")).toBeInTheDocument();
});
