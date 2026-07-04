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
