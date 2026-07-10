// The Command Center's shared surface vocabulary (Wave F consolidation).
// These were duplicated inline across the dashboard / clients / client-detail
// pages; one module now owns the ink ops-room idiom: paper-on-ink panels,
// serif section headers, restrained pills, and the compact relative clock.
// Server-renderable on purpose — no "use client".

import type { ReactNode, HTMLAttributes } from "react";

import type { AccessStatus } from "@ov-black/api-client";

export function Panel({
  children,
  className = "",
  ...rest
}: {
  children: ReactNode;
} & HTMLAttributes<HTMLElement>) {
  return (
    <section
      {...rest}
      className={`flex flex-col gap-4 rounded-md border border-paper/10 bg-paper/5 p-5 sm:p-7 ${className}`}
    >
      {children}
    </section>
  );
}

export function SectionHeader({
  id,
  title,
  eyebrow,
  actions,
}: {
  id?: string;
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-paper/10 pb-3">
      <h2 id={id} className="font-serif text-2xl tracking-tight text-paper">
        {title}
      </h2>
      <div className="flex items-baseline gap-4">
        {eyebrow ? (
          <span className="font-sans text-[10px] uppercase tracking-label text-paper/55">
            {eyebrow}
          </span>
        ) : null}
        {actions}
      </div>
    </div>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="font-sans text-sm italic text-paper/55">{children}</p>;
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return (
    <div className="border border-destructive/40 bg-destructive/10 p-4 font-sans text-sm text-destructive-foreground">
      {children}
    </div>
  );
}

const PILL_BASE =
  "inline-block rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em]";

export function StatusPill({ status }: { status: string }) {
  const tone =
    status === "approved"
      ? "border-paper/40 text-paper"
      : status === "with_traveler"
        ? "border-brand/40 text-brand"
        : "border-paper/15 text-paper/65";
  const label =
    status === "in_studio"
      ? "In studio"
      : status === "with_traveler"
        ? "With traveler"
        : status;
  return <span className={`${PILL_BASE} ${tone}`}>{label}</span>;
}

export function InvitePill({ status }: { status: AccessStatus }) {
  const copy =
    status === "active" ? "Active" : status === "pending" ? "Pending" : "Uninvited";
  const tone =
    status === "active"
      ? "border-paper/40 text-paper"
      : status === "pending"
        ? "border-brand/40 text-brand"
        : "border-paper/20 text-paper/50";
  return <span className={`${PILL_BASE} ${tone}`}>{copy}</span>;
}

export function InvoiceStatusPill({ status }: { status: string }) {
  const tone =
    status === "paid"
      ? "border-paper/40 text-paper"
      : status === "issued"
        ? "border-brand/40 text-brand"
        : status === "void"
          ? "border-paper/15 text-paper/40 line-through"
          : "border-paper/15 text-paper/65";
  return <span className={`${PILL_BASE} ${tone}`}>{status}</span>;
}

/** Compact "how long ago" — the roster clock ("Today", "3d ago", "Jun 2"). */
export function relativeDay(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const days = Math.floor((now.getTime() - then.getTime()) / (1000 * 60 * 60 * 24));
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(then);
}

/** Mono money rendering — figures are data, not prose. */
export function money(amount: string | number, currency: string): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (Number.isNaN(value)) return `${amount} ${currency}`;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: value % 1 === 0 ? 0 : 2,
  }).format(value);
}
