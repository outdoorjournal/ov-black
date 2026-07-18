// Render proof for the Journal's night treatment with lodging presence
// (kernel `nightly_lodging`): a roofed night trades the ☾ for the hotel's
// icon-in-circle on the spine, and both the circle and the caption activate
// the hotel card — "where am I sleeping tonight" is one tap from the night.

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { NightSegment } from "@/app/_components/itinerary-graph/views/journal/Spine";

describe("NightSegment · lodging presence", () => {
  test("a roofed night wears the hotel icon-in-circle and activates the card", () => {
    const onActivate = vi.fn();
    render(
      <NightSegment
        lodging={{ nodeId: "h1", title: "Grand Hotel" }}
        onActivateLodging={onActivate}
      />,
    );
    // The circle replaces the generic ☾ tick and is a real button.
    fireEvent.click(screen.getByTestId("journal-night-lodging-circle"));
    expect(onActivate).toHaveBeenCalledWith("h1");
    // The caption is the second click target for the same gesture.
    fireEvent.click(screen.getByTestId("journal-night-lodging"));
    expect(onActivate).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Night · Grand Hotel")).toBeInTheDocument();
  });

  test("a night_bar title outranks the roof's name but keeps the hotel click", () => {
    const onActivate = vi.fn();
    render(
      <NightSegment
        title="Overnight ferry"
        lodging={{ nodeId: "h1", title: "Grand Hotel" }}
        onActivateLodging={onActivate}
      />,
    );
    expect(screen.getByText("Night · Overnight ferry")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("journal-night-lodging"));
    expect(onActivate).toHaveBeenCalledWith("h1");
  });

  test("a roofless night keeps the plain caption and offers no click", () => {
    render(<NightSegment />);
    expect(
      screen.queryByTestId("journal-night-lodging-circle"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("journal-night-lodging")).not.toBeInTheDocument();
    expect(screen.getByText("Night")).toBeInTheDocument();
  });

  test("a roof without the activate gesture still shows the circle, inert", () => {
    // Some render paths may not wire the gesture (e.g. read-only surfaces):
    // presence still shows, nothing is clickable.
    render(<NightSegment lodging={{ nodeId: "h1", title: "Grand Hotel" }} />);
    const circle = screen.getByTestId("journal-night-lodging-circle");
    expect(circle.tagName).not.toBe("BUTTON");
    expect(screen.queryByTestId("journal-night-lodging")).not.toBeInTheDocument();
    expect(screen.getByText("Night · Grand Hotel")).toBeInTheDocument();
  });
});
