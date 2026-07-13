import { type Page, expect, test } from "@playwright/test";

import { enterFreshBuilder } from "../support/builder";

// ITB-6 / ITB-6A — the builder shouldn't show a *dated* timeline before it knows
// *when*. With a vague brief (window/flexible) and an empty board, a date grid is
// meaningless (it would be synthesized around "today"), so only the concierge
// empty-state shows. Exact dates — or anything already on the board — bring the
// timeline back. Timing is now captured on the builder's hero (see intake.spec),
// so we seed it there and then look at the Timeline view's scaffold.

const header = (page: Page) => page.getByTestId("itinerary-graph-header");

// ITB-6 — a vague brief keeps the dated timeline hidden.
test("ITB-6: a vague brief (no dates yet) hides the dated timeline", async ({
  page,
  baseURL,
}) => {
  const { id } = await enterFreshBuilder(page, baseURL!, {
    brief: "Somewhere warm, sometime",
    timing: { kind: "flexible" },
  });
  await page.goto(`/itinerary/${id}/timeline`);

  // Only the concierge guidance — no dated grid behind it.
  await expect(
    page.getByRole("heading", { name: "A blank canvas, ready when you are" }),
  ).toBeVisible();
  await expect(header(page)).toHaveAttribute("data-timeline-visible", "false");
});

// ITB-6A — knowing the exact dates is enough to (optionally) show the timeline.
test("ITB-6A: exact dates bring the timeline back", async ({ page, baseURL }) => {
  const { id } = await enterFreshBuilder(page, baseURL!, {
    brief: "A week in Lisbon",
    timing: { kind: "exact", dateStart: "2027-05-10", dateEnd: "2027-05-17" },
  });
  await page.goto(`/itinerary/${id}/timeline`);
  await expect(header(page)).toHaveAttribute("data-timeline-visible", "true");
});
