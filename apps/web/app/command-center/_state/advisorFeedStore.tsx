"use client";

// The Command Center's live-feed store (Wave F) — one per advisor shell,
// mounted by AdvisorLiveProvider in the layout. Pages seed their own slices
// via server props; this store carries only what moves without a navigation:
// live events, session pulses, and the connection state. The reducer is pure
// (lib/advisorFeed.ts); the transport (useAdvisorFeed) dispatches into here.

import { createStoreContext } from "@/lib/store/createStoreContext";
import {
  type AdvisorFrame,
  type FeedConnection,
  type FeedState,
  feedReducer,
  initialFeedState,
} from "@/lib/advisorFeed";

export type AdvisorFeedStoreState = FeedState & {
  applyFrame: (frame: AdvisorFrame) => void;
  setConnection: (connection: FeedConnection) => void;
};

const store = createStoreContext<AdvisorFeedStoreState, undefined>(
  () => (set) => ({
    ...initialFeedState(),
    applyFrame: (frame) =>
      set((state) => feedReducer(state, frame)),
    setConnection: (connection) => set({ connection }),
  }),
  "AdvisorFeed",
);

export const AdvisorFeedProvider = store.Provider;
export const useAdvisorFeedStore = store.useStore;
export const useAdvisorFeedStoreApi = store.useStoreApi;
