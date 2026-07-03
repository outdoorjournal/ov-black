"use client";

// Gates the builder on the first-run intake (0033). When the itinerary has no
// brief yet, we show the intake (capture the goal + timing) FIRST; once saved
// — or skipped — the timeline builder takes over in place. Same surface for an
// advisor and a self-serve traveler; the audience only changes the wording.
//
// The graph is not mounted behind the intake: a fresh itinerary has an empty
// timeline, so there is nothing to render underneath, and deferring the mount
// keeps the concierge session from opening before the trip even has a goal.

import { useState } from "react";

import {
  ItineraryGraphView,
  type ItineraryGraphViewProps,
} from "../ItineraryGraphView";
import {
  ItineraryIntake,
  type ItineraryIntakeInitial,
} from "./ItineraryIntake";

export type ItineraryBuilderScreenProps = ItineraryGraphViewProps & {
  /** True when the itinerary has no brief yet — show the intake gate first. */
  needsBrief: boolean;
  audience: "advisor" | "traveler";
  intakeInitial?: ItineraryIntakeInitial;
};

export function ItineraryBuilderScreen({
  needsBrief,
  audience,
  intakeInitial,
  ...graphProps
}: ItineraryBuilderScreenProps) {
  const [showIntake, setShowIntake] = useState(needsBrief);

  if (showIntake && graphProps.apiBaseUrl && graphProps.accessToken) {
    return (
      <ItineraryIntake
        itineraryId={graphProps.itineraryId}
        apiBaseUrl={graphProps.apiBaseUrl}
        accessToken={graphProps.accessToken}
        audience={audience}
        initial={intakeInitial}
        onSaved={() => setShowIntake(false)}
        onSkip={() => setShowIntake(false)}
      />
    );
  }

  return <ItineraryGraphView {...graphProps} embedded />;
}
