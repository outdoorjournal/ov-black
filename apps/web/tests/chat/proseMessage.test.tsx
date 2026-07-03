// ProseMessage is the single client-side render change that unlocks rich
// concierge replies. These lock the three behaviours that matter:
//   1. plain markdown (emphasis + lists) actually renders — no more wall of text
//   2. a `place:` link becomes an inline, collapsed-by-default place chip
//   3. an ```ov-timeline fenced block becomes the vertical timeline, with the
//      surrounding prose intact and a graceful fallback on malformed JSON.

import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ProseMessage } from "@/app/chat/[client_id]/_components/ProseMessage";

test("renders markdown emphasis and lists instead of raw text", () => {
  render(
    <ProseMessage
      content={"Settled — **16–23 August**.\n\n- Ionian Discoveries\n- Vathos Sailing"}
    />,
  );

  expect(screen.getByText("16–23 August").tagName).toBe("STRONG");
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("renders a place: link as a collapsed place chip", () => {
  render(
    <ProseMessage content={"Three operators in [Fiskardo](place:Fiskardo) harbour."} />,
  );

  const chip = screen.getByTestId("place-chip");
  expect(chip).toHaveTextContent("Fiskardo");
  expect(chip).toHaveAttribute("data-place-query", "Fiskardo");
  // No map is drawn until the chip is tapped.
  expect(screen.queryByTestId("place-chip-map")).not.toBeInTheDocument();
});

test("renders an ov-timeline fenced block as the timeline, keeping surrounding prose", () => {
  const data = {
    caption: "The shape of the week",
    days: [
      { label: "Day 1", title: "Arrive Fiskardo", detail: "embark, settle" },
      { label: "Days 2–3", title: "North toward Lefkada" },
    ],
  };
  const content =
    "Here's how I'd shape it:\n\n```ov-timeline\n" +
    JSON.stringify(data) +
    "\n```\n\nShall I place cards?";

  render(<ProseMessage content={content} />);

  const timeline = screen.getByTestId("chat-timeline");
  expect(timeline).toHaveTextContent("The shape of the week");
  expect(timeline).toHaveTextContent("Arrive Fiskardo");
  expect(timeline).toHaveTextContent("North toward Lefkada");
  expect(screen.getByText(/Shall I place cards/)).toBeInTheDocument();
});

test("falls back without crashing when the timeline JSON is malformed", () => {
  render(<ProseMessage content={"```ov-timeline\n{not valid json}\n```"} />);

  expect(screen.queryByTestId("chat-timeline")).not.toBeInTheDocument();
});
