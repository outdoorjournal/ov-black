"use client";

// Lets a deep advisor page feed a display name up to the shared masthead
// breadcrumbs, which are otherwise derived only from the pathname (and so can't
// know a specific client's name). The client workspace registers its name via
// SetClientCrumb; CommandCenterChrome reads it for the trailing crumb, so the
// masthead shows "Clients › Ada Lovelace" instead of a generic "Clients › Client".

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type CrumbContextValue = {
  clientLabel: string | null;
  setClientLabel: (label: string | null) => void;
};

const CommandCenterCrumbContext = createContext<CrumbContextValue | null>(null);

export function CommandCenterCrumbProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [clientLabel, setClientLabel] = useState<string | null>(null);
  const value = useMemo(
    () => ({ clientLabel, setClientLabel }),
    [clientLabel],
  );
  return (
    <CommandCenterCrumbContext.Provider value={value}>
      {children}
    </CommandCenterCrumbContext.Provider>
  );
}

export function useCommandCenterCrumb(): CrumbContextValue {
  // Outside the provider (shouldn't happen under /command-center) the crumb is
  // simply absent — the pathname-derived crumbs still render.
  return (
    useContext(CommandCenterCrumbContext) ?? {
      clientLabel: null,
      setClientLabel: () => {},
    }
  );
}

/** Registers a client's display name as the active detail breadcrumb. */
export function SetClientCrumb({ name }: { name: string }) {
  const { setClientLabel } = useCommandCenterCrumb();
  useEffect(() => {
    setClientLabel(name);
    return () => setClientLabel(null);
  }, [name, setClientLabel]);
  return null;
}
