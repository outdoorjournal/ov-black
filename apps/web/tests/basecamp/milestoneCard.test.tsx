// The onboarding milestone card renders only for a "milestone" turn (the
// client-synthesized row committed when onboarding_complete flips true), not
// for ordinary assistant/user turns. This locks the role→card mapping in
// ConversationStream so the milestone signal can't silently stop rendering.

import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ConversationStream } from "@/app/chat/[client_id]/_components/ConversationStream";
import type { AgentTurnView } from "@/app/chat/[client_id]/_components/types";

test("renders the milestone card for a milestone turn", () => {
  const turns: AgentTurnView[] = [
    { id: "u1", turn_index: 0, role: "user", content: "I love onsen ryokans" },
    { id: "m1", turn_index: 1, role: "milestone", content: "" },
  ];
  render(<ConversationStream turns={turns} streaming={null} />);

  expect(screen.getByTestId("onboarding-milestone-card")).toBeInTheDocument();
  expect(screen.getByText(/feel for you/i)).toBeInTheDocument();
});

test("does not render a milestone card for ordinary turns", () => {
  const turns: AgentTurnView[] = [
    { id: "a1", turn_index: 0, role: "assistant", content: "Tell me more." },
  ];
  render(<ConversationStream turns={turns} streaming={null} />);

  expect(screen.queryByTestId("onboarding-milestone-card")).not.toBeInTheDocument();
});
