"use client";

// The Command Center's ⌘K palette (Wave F). One provider owns the open state
// and the global hotkey; the masthead trigger and the cmdk dialog both hang
// off it. Static nav actions are filtered locally (pure, _lib/palette.ts);
// client + trip results come from the same paged roster endpoints the tables
// use (`?q=`), debounced 150ms with a stale-response guard — no separate
// search route at boutique scale. Browser auth follows the AdvisorLive
// precedent: browser Supabase session, fresh token per search.

import { Command } from "cmdk";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  type AdvisorItinerarySummary,
  type ClientSummary,
  createApiClient,
  listAdvisorItineraries,
  listClients,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createBrowserSupabase } from "@/lib/supabase/client";

import {
  PALETTE_MIN_SEARCH_LENGTH,
  PALETTE_SEARCH_DEBOUNCE_MS,
  filterNavActions,
} from "../_lib/palette";

type PaletteContextValue = {
  open: boolean;
  setOpen: (open: boolean) => void;
};

const PaletteContext = createContext<PaletteContextValue | null>(null);

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  // The palette's own search input shouldn't swallow the toggle chord.
  if (target.closest("[cmdk-root]")) return false;
  const tag = target.tagName;
  return (
    target.isContentEditable ||
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT"
  );
}

export function CommandPaletteProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        if (isEditableTarget(e.target)) return;
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const value = useMemo(() => ({ open, setOpen }), [open]);

  return (
    <PaletteContext.Provider value={value}>
      {children}
      <PaletteDialog />
    </PaletteContext.Provider>
  );
}

/** Masthead search trigger — composed with LiveIndicator in the actions slot. */
export function CommandPaletteTrigger() {
  const ctx = useContext(PaletteContext);
  if (!ctx) return null;
  return (
    <button
      type="button"
      onClick={() => ctx.setOpen(true)}
      aria-label="Open command palette"
      data-testid="palette-trigger"
      className="flex items-center gap-2 rounded-full border border-paper/20 px-3 py-1 font-sans text-xs text-paper/55 transition-colors hover:border-paper/40 hover:text-paper focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
    >
      <span className="hidden sm:inline">Search</span>
      <kbd className="font-mono text-[10px] tracking-[0.1em]">⌘K</kbd>
    </button>
  );
}

function PaletteDialog() {
  const ctx = useContext(PaletteContext);
  const router = useRouter();
  const { apiBaseUrl } = publicEnv();

  const [query, setQuery] = useState("");
  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [trips, setTrips] = useState<AdvisorItinerarySummary[]>([]);
  const [searching, setSearching] = useState(false);
  // Monotonic ticket per keystroke: the wrappers don't take an AbortSignal, so
  // a late response from a superseded query is dropped instead of cancelled.
  const searchSeq = useRef(0);

  const getAccessToken = useMemo<() => Promise<string | null>>(() => {
    let supabase: ReturnType<typeof createBrowserSupabase> | null = null;
    try {
      supabase = createBrowserSupabase();
    } catch {
      supabase = null;
    }
    return async () => {
      if (!supabase) return null;
      const {
        data: { session },
      } = await supabase.auth.getSession();
      return session?.access_token ?? null;
    };
  }, []);

  const open = ctx?.open ?? false;

  useEffect(() => {
    if (!open) {
      setQuery("");
      setClients([]);
      setTrips([]);
      setSearching(false);
      searchSeq.current += 1;
      return;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    const seq = ++searchSeq.current;
    if (q.length < PALETTE_MIN_SEARCH_LENGTH) {
      setClients([]);
      setTrips([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    const timer = setTimeout(() => {
      void (async () => {
        const token = await getAccessToken();
        if (searchSeq.current !== seq) return;
        const api = createApiClient(
          token
            ? { baseUrl: apiBaseUrl, accessToken: token }
            : { baseUrl: apiBaseUrl },
        );
        const [clientsResult, tripsResult] = await Promise.all([
          listClients(api, { q, limit: 8 }),
          listAdvisorItineraries(api, { q, limit: 8 }),
        ]);
        if (searchSeq.current !== seq) return;
        setClients(clientsResult.ok ? clientsResult.clients : []);
        setTrips(tripsResult.ok ? tripsResult.itineraries : []);
        setSearching(false);
      })();
    }, PALETTE_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [open, query, getAccessToken, apiBaseUrl]);

  if (!ctx) return null;

  const navActions = filterNavActions(query);
  const searched = query.trim().length >= PALETTE_MIN_SEARCH_LENGTH;
  const noMatches =
    searched &&
    !searching &&
    navActions.length === 0 &&
    clients.length === 0 &&
    trips.length === 0;

  const go = (href: Route) => {
    ctx.setOpen(false);
    router.push(href);
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={ctx.setOpen}
      label="Command palette"
      // Filtering is ours: nav is matched locally, rosters server-side.
      shouldFilter={false}
      overlayClassName="fixed inset-0 z-50 bg-ink/70 backdrop-blur-sm"
      contentClassName="fixed left-1/2 top-24 z-50 w-[min(40rem,calc(100vw-2rem))] -translate-x-1/2"
    >
      <div className="overflow-hidden rounded-md border border-paper/15 bg-ink text-paper shadow-2xl shadow-black/60">
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search clients, trips, or jump anywhere…"
          className="w-full border-b border-paper/10 bg-transparent px-5 py-4 font-sans text-sm text-paper outline-none placeholder:text-paper/40"
        />
        <Command.List className="max-h-[22rem] overflow-y-auto p-2">
          {searching ? (
            <Command.Loading>
              <p className="px-3 py-2 font-mono text-[10px] uppercase tracking-[0.2em] text-paper/40">
                Searching…
              </p>
            </Command.Loading>
          ) : null}
          {noMatches ? (
            <Command.Empty>
              <p className="px-3 py-6 text-center font-sans text-sm italic text-paper/45">
                Nothing matches “{query.trim()}”.
              </p>
            </Command.Empty>
          ) : null}

          {navActions.length > 0 ? (
            <Command.Group heading={<GroupHeading>Go to</GroupHeading>}>
              {navActions.map((action) => (
                <PaletteItem
                  key={action.id}
                  value={action.id}
                  onSelect={() => go(action.href)}
                >
                  <span className="font-sans text-sm">{action.label}</span>
                </PaletteItem>
              ))}
            </Command.Group>
          ) : null}

          {clients.length > 0 ? (
            <Command.Group heading={<GroupHeading>Clients</GroupHeading>}>
              {clients.map((c) => (
                <PaletteItem
                  key={c.id}
                  value={`client-${c.id}`}
                  onSelect={() => go(`/command-center/clients/${c.id}`)}
                >
                  <span className="min-w-0 truncate font-serif text-sm tracking-tight">
                    {c.full_name}
                  </span>
                  <span className="ml-auto truncate pl-4 font-sans text-xs text-paper/45">
                    {c.email}
                  </span>
                </PaletteItem>
              ))}
            </Command.Group>
          ) : null}

          {trips.length > 0 ? (
            <Command.Group heading={<GroupHeading>Trips</GroupHeading>}>
              {trips.map((t) => (
                <PaletteItem
                  key={t.id}
                  value={`trip-${t.id}`}
                  onSelect={() => go(`/itinerary/${t.id}`)}
                >
                  <span className="min-w-0 truncate font-serif text-sm tracking-tight">
                    {t.title || "Untitled draft"}
                  </span>
                  <span className="ml-auto truncate pl-4 font-sans text-xs text-paper/45">
                    {t.client.full_name} · {t.status}
                  </span>
                </PaletteItem>
              ))}
            </Command.Group>
          ) : null}
        </Command.List>
      </div>
    </Command.Dialog>
  );
}

function GroupHeading({ children }: { children: ReactNode }) {
  return (
    <span className="block px-3 pb-1 pt-3 font-sans text-[10px] uppercase tracking-label text-paper/40">
      {children}
    </span>
  );
}

function PaletteItem({
  value,
  onSelect,
  children,
}: {
  value: string;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex cursor-pointer items-center rounded-sm px-3 py-2 text-paper/80 data-[selected=true]:bg-paper/10 data-[selected=true]:text-paper"
    >
      {children}
    </Command.Item>
  );
}
