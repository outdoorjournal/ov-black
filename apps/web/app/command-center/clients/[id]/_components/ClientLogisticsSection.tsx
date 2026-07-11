"use client";

import { useState, useTransition } from "react";

import type { ClientDetail } from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { updateClientLogisticsAction } from "../actions";

// A short convenience list for the currency datalist — the traveler's
// preferred display currency (drives read-time FX conversion of totals and
// what the agent quotes in). Any ISO 4217 code is accepted; these are just
// the ones an advisor reaches for most.
const COMMON_CURRENCIES = ["USD", "EUR", "GBP", "CHF", "JPY", "AUD", "CAD", "AED"];

const THREE_LETTERS = /^[A-Za-z]{3}$/;

export function ClientLogisticsSection({
  clientId,
  address,
  favoriteAirport,
  preferredCurrency,
}: {
  clientId: string;
  address: string | null;
  favoriteAirport: string | null;
  preferredCurrency: string | null;
}) {
  const [editing, setEditing] = useState(false);
  const [draftAddress, setDraftAddress] = useState(address ?? "");
  const [draftAirport, setDraftAirport] = useState(favoriteAirport ?? "");
  const [draftCurrency, setDraftCurrency] = useState(preferredCurrency ?? "");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const reset = () => {
    setDraftAddress(address ?? "");
    setDraftAirport(favoriteAirport ?? "");
    setDraftCurrency(preferredCurrency ?? "");
    setError(null);
  };

  const onCancel = () => {
    reset();
    setEditing(false);
  };

  const onSave = () => {
    const airport = draftAirport.trim().toUpperCase();
    const currency = draftCurrency.trim().toUpperCase();
    if (airport && !THREE_LETTERS.test(airport)) {
      setError("Airport must be a 3-letter IATA code (e.g. JFK).");
      return;
    }
    if (currency && !THREE_LETTERS.test(currency)) {
      setError("Currency must be a 3-letter ISO code (e.g. USD).");
      return;
    }
    setError(null);
    // Send explicit nulls to clear a field the advisor emptied.
    const payload = {
      address: draftAddress.trim() || null,
      favorite_airport: airport || null,
      preferred_currency: currency || null,
    };
    startTransition(async () => {
      const result = await updateClientLogisticsAction(clientId, payload);
      if ("error" in result) {
        setError(result.error);
      } else {
        setEditing(false);
      }
    });
  };

  if (!editing) {
    return (
      <div className="flex flex-col gap-4">
        <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          <ReadField label="Preferred currency" value={preferredCurrency} />
          <ReadField label="Favorite airport" value={favoriteAirport} />
          <div className="sm:col-span-2 lg:col-span-1">
            <ReadField label="Address" value={address} />
          </div>
        </dl>
        <div>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-paper"
          >
            Edit
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
      className="flex flex-col gap-3"
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55">
            Preferred currency
          </span>
          <Input
            list="ovb-currency-codes"
            placeholder="USD"
            value={draftCurrency}
            maxLength={3}
            onChange={(e) => setDraftCurrency(e.target.value.toUpperCase())}
            className="h-9 border-paper/20 bg-transparent uppercase text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
          <datalist id="ovb-currency-codes">
            {COMMON_CURRENCIES.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55">
            Favorite airport
          </span>
          <Input
            placeholder="JFK"
            value={draftAirport}
            maxLength={3}
            onChange={(e) => setDraftAirport(e.target.value.toUpperCase())}
            className="h-9 border-paper/20 bg-transparent uppercase text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
        </label>
        <label className="flex flex-col gap-1 sm:col-span-2 lg:col-span-1">
          <span className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55">
            Address
          </span>
          <Input
            placeholder="Street, city, country"
            value={draftAddress}
            onChange={(e) => setDraftAddress(e.target.value)}
            className="h-9 border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
        </label>
      </div>
      <div className="flex gap-1">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={isPending}
          className="text-paper/70 hover:bg-paper/10 hover:text-paper"
        >
          Cancel
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={isPending}
          className="bg-paper text-ink hover:bg-paper/90"
        >
          {isPending ? "saving…" : "Save"}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="font-sans text-xs font-medium text-destructive">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function ReadField({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55">
        {label}
      </dt>
      <dd className="font-sans text-sm text-paper/90">{value || "—"}</dd>
    </div>
  );
}
