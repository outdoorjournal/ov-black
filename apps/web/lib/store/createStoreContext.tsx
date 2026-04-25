"use client";

// Per-instance scoped zustand store backed by a React context.
//
// Most state in this app is keyed by a route entity — a chat session, a
// draft itinerary, a prototype timeline. A singleton store would leak state
// across navigations, so we wrap `createStore` in a context whose value is
// owned by a Provider that lives at the route boundary. The store is created
// once via `useRef` (idempotent under StrictMode double-invocation) and seeded
// from the Provider's `initial` prop.
//
// Usage:
//   const { Provider, useStore, useStoreApi } = createStoreContext<State, Init>(
//     (initial) => (set, get) => ({ ...initialState(initial), action: () => set(...) }),
//     "MyStore",
//   );
//
//   <Provider initial={...}>...consumers call useStore(selector)...</Provider>

import { createContext, useContext, useRef, type ReactNode } from "react";
import {
  createStore,
  useStore as useZustandStore,
  type StateCreator,
  type StoreApi,
} from "zustand";

export interface StoreContext<TState, TInit> {
  Provider: (props: { initial: TInit; children: ReactNode }) => ReactNode;
  useStore: <U>(selector: (state: TState) => U) => U;
  useStoreApi: () => StoreApi<TState>;
}

export function createStoreContext<TState, TInit>(
  init: (initial: TInit) => StateCreator<TState>,
  displayName: string,
): StoreContext<TState, TInit> {
  const Context = createContext<StoreApi<TState> | null>(null);
  Context.displayName = `${displayName}StoreContext`;

  function Provider({
    initial,
    children,
  }: {
    initial: TInit;
    children: ReactNode;
  }): ReactNode {
    const ref = useRef<StoreApi<TState> | null>(null);
    if (ref.current === null) {
      ref.current = createStore<TState>()(init(initial));
    }
    return <Context.Provider value={ref.current}>{children}</Context.Provider>;
  }

  function useStore<U>(selector: (state: TState) => U): U {
    const store = useContext(Context);
    if (!store) {
      throw new Error(
        `${displayName}: useStore called outside of Provider. Wrap your tree in <Provider initial={...}>.`,
      );
    }
    return useZustandStore(store, selector);
  }

  function useStoreApi(): StoreApi<TState> {
    const store = useContext(Context);
    if (!store) {
      throw new Error(
        `${displayName}: useStoreApi called outside of Provider.`,
      );
    }
    return store;
  }

  return { Provider, useStore, useStoreApi };
}
