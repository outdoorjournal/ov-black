"use client";

// The hero's "Download" affordance — export the itinerary the viewer is looking
// at (trunk or their fork; the route is per-version, so store.itineraryId is
// already the right one) as a PDF or an Excel file. Both roles see it. A small
// chip mirroring the hero's money callout / party chip, opening a two-item menu.
//
// The bytes come back as a Blob from the API (Content-Disposition names the
// file); we object-URL it and click a synthetic <a download>. Craft-feel: no
// spinner — the menu item's label swaps to "Preparing…" while in flight; a
// failure shows a quiet inline line that clears itself.

import { useCallback, useEffect, useRef, useState } from "react";

import { createApiClient, downloadItineraryExport } from "@ov-black/api-client";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

type Format = "pdf" | "xlsx";

function DownloadIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M10 3v10" />
      <path d="M5.5 8.5 10 13l4.5-4.5" />
      <path d="M3.5 16.5h13" />
    </svg>
  );
}

export function DownloadMenu() {
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<Format | null>(null);
  const [error, setError] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const errorTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const ready = apiBaseUrl !== null && accessToken !== null;

  // Escape + click-outside dismiss (mirrors the hero's other popovers).
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (e.target instanceof Node && rootRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(
    () => () => {
      if (errorTimer.current) clearTimeout(errorTimer.current);
    },
    [],
  );

  const download = useCallback(
    async (format: Format) => {
      if (!apiBaseUrl || !accessToken || busy) return;
      setBusy(format);
      setError(false);
      const client = createApiClient({ baseUrl: apiBaseUrl, accessToken });
      const result = await downloadItineraryExport(client, itineraryId, format);
      setBusy(null);
      if (!result.ok) {
        setError(true);
        if (errorTimer.current) clearTimeout(errorTimer.current);
        errorTimer.current = setTimeout(() => setError(false), 5000);
        return;
      }
      const url = URL.createObjectURL(result.blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = result.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setOpen(false);
    },
    [apiBaseUrl, accessToken, itineraryId, busy],
  );

  if (!ready) return null;

  const itemCls =
    "flex w-full items-center justify-between gap-6 px-3 py-2 text-left font-sans text-[12px] text-ink/80 transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50";

  return (
    <div className="absolute left-4 top-4 z-10 sm:left-6 sm:top-6" ref={rootRef}>
      <button
        type="button"
        data-testid="hero-download"
        aria-label="Download this itinerary"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="group/hero-field inline-flex items-center gap-2 rounded-full border border-white/25 bg-black/25 px-3 py-1.5 font-sans text-[12px] text-white/85 backdrop-blur-sm transition-colors hover:bg-black/40"
      >
        <DownloadIcon />
        <span>Download</span>
      </button>

      {open ? (
        <div
          data-testid="hero-download-menu"
          className="absolute left-0 top-full mt-2 w-48 overflow-hidden rounded-lg border border-ink/10 bg-paper py-1 text-ink shadow-xl"
        >
          <button
            type="button"
            data-testid="hero-download-pdf"
            disabled={busy !== null}
            onClick={() => void download("pdf")}
            className={itemCls}
          >
            <span>PDF</span>
            <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/40">
              {busy === "pdf" ? "Preparing…" : "Full itinerary"}
            </span>
          </button>
          <button
            type="button"
            data-testid="hero-download-xlsx"
            disabled={busy !== null}
            onClick={() => void download("xlsx")}
            className={itemCls}
          >
            <span>Excel</span>
            <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/40">
              {busy === "xlsx" ? "Preparing…" : "Timeline"}
            </span>
          </button>
        </div>
      ) : null}

      {error ? (
        <p
          data-testid="hero-download-error"
          className="absolute left-0 top-full mt-2 w-52 rounded-md bg-black/70 px-3 py-2 font-sans text-[11px] text-white/85 backdrop-blur-sm"
        >
          Couldn’t prepare the file — please try again.
        </p>
      ) : null}
    </div>
  );
}
