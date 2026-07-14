// Restrained line icons for the planner shell rails (stroke = currentColor).
// Geometric, not emoji — holds the craft line (R014). Shared by the desktop
// Rail and the MobileTabBar so a destination reads the same in both.

const BASE = {
  width: 20,
  height: 20,
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.4,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function DashboardIcon() {
  return (
    <svg {...BASE} aria-hidden>
      <path d="M3 8.5 10 3l7 5.5" />
      <path d="M5 8v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V8" />
      <path d="M8 17v-4.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1V17" />
    </svg>
  );
}

export function TimelineIcon() {
  return (
    <svg {...BASE} aria-hidden>
      <rect x="3" y="4" width="4" height="12" rx="1" />
      <rect x="9" y="4" width="4" height="8" rx="1" />
      <rect x="15" y="4" width="2" height="12" rx="1" />
    </svg>
  );
}

export function CollectionIcon() {
  return (
    <svg {...BASE} aria-hidden>
      <rect x="3" y="6" width="10" height="10" rx="1.5" />
      <path d="M7 6V4.5A1.5 1.5 0 0 1 8.5 3H16a1 1 0 0 1 1 1v8a1.5 1.5 0 0 1-1.5 1.5H13" />
    </svg>
  );
}

export function ReadingIcon() {
  return (
    <svg {...BASE} aria-hidden>
      {/* An open book — two pages spread from a central spine. */}
      <path d="M10 5.5C8.5 4.3 6.4 4 3.5 4.2v10C6.4 14 8.5 14.3 10 15.5" />
      <path d="M10 5.5C11.5 4.3 13.6 4 16.5 4.2v10c-2.9-.2-5 .1-6.5 1.3" />
      <path d="M10 5.5v10" />
    </svg>
  );
}

export function StudioIcon() {
  return (
    <svg {...BASE} aria-hidden>
      <path d="M4 16 14 6l1.8-1.8a1.4 1.4 0 0 1 2 2L16 8 6 18l-3 1 1-3Z" />
      <path d="M12.5 7.5 15 10" />
    </svg>
  );
}

export function ConciergeIcon() {
  return (
    <svg {...BASE} aria-hidden>
      <path d="M4 14a6 6 0 1 1 12 0" />
      <path d="M3 14h14" />
      <path d="M10 4v2" />
    </svg>
  );
}

export function InvoiceIcon() {
  return (
    <svg {...BASE} aria-hidden>
      {/* A receipt: paper with a torn/zigzag foot and a couple of line items. */}
      <path d="M5 3h10v14l-2-1.2L11 17l-2-1.2L7 17l-2-1.2V3Z" />
      <path d="M8 7h4" />
      <path d="M8 10.5h4" />
    </svg>
  );
}

export function VaultIcon() {
  return (
    <svg {...BASE} aria-hidden>
      {/* A safe: a bordered box with a combination dial. */}
      <rect x="3" y="4" width="14" height="12" rx="1.5" />
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 10v-1.4M12.6 10H14" />
    </svg>
  );
}

export function BookingIcon() {
  return (
    <svg {...BASE} aria-hidden>
      {/* A ticket with a confirming check. */}
      <path d="M4 6h12v3a1.5 1.5 0 0 0 0 2v3H4v-3a1.5 1.5 0 0 0 0-2V6Z" />
      <path d="M8 9.8l1.4 1.4L12 8.5" />
    </svg>
  );
}

export function PartyIcon() {
  return (
    <svg {...BASE} aria-hidden>
      {/* Two travelers — a near figure and a companion behind. */}
      <circle cx="7.5" cy="7" r="2.6" />
      <path d="M3 16.5a4.5 4.5 0 0 1 9 0" />
      <path d="M13.2 5.2a2.6 2.6 0 0 1 0 5.1" />
      <path d="M14 11.6a4.5 4.5 0 0 1 3 4.9" />
    </svg>
  );
}
