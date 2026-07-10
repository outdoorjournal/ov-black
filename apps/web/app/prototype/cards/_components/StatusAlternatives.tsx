"use client";

import type { ReactNode } from "react";

import { NOISE_BG, TYPE_TOKENS, type StatusKind } from "@/app/_components/itinerary-graph/shared/cards/tokens";

const t = TYPE_TOKENS.experience;

// All alternatives render the same experience-card content so the only
// visible variable is the status treatment.

const STATUSES: StatusKind[] = ["approved", "booked", "confirmed"];

const SERIAL: Record<StatusKind, string | null> = {
  pending: null,
  approved: null,
  booked: "URASEN-AC-2904",
  confirmed: "URASEN-AC-2904 · Mar 12, 2026",
  discarded: null,
};

const STATUS_DATE: Record<StatusKind, string> = {
  pending: "",
  approved: "Mar 10",
  booked: "Mar 12",
  confirmed: "Mar 12, 2026",
  discarded: "",
};

export function StatusAlternatives() {
  return (
    <div className="space-y-10">
      <Alternative
        id="A"
        title="Wax seal"
        thesis="A circular embossed seal stamps the card. Booked is a small lock medallion; Confirmed is a full wax seal with the serial along the perimeter. Trades off cuteness for the right ceremonial weight."
        Component={WaxSealCard}
      />
      <Alternative
        id="B"
        title="Folded paper corner"
        thesis="The top-right corner of the card folds over. The fold deepens with status — Approved is a small tan flap, Booked grows it, Confirmed is a deep ink fold with foil-printed serial. Reads as a sealed envelope."
        Component={FoldCornerCard}
      />
      <Alternative
        id="C"
        title="Manifest footer band"
        thesis="The status moves out of the corner entirely into a dedicated full-width band along the bottom edge. Confirmed inverts to ink-on-paper with the confirmation number engraved. Most utilitarian; reads like a luggage-tag stub."
        Component={FooterBandCard}
      />
      <Alternative
        id="D"
        title="Substrate weight"
        thesis="The card itself escalates physically. Confirmed swaps to a heavier card stock (deeper cream), gains a thicker double-line border, deeper shadow, and embosses CONFIRMED + serial into the bottom edge. The card visibly weighs more — hardest to “move”."
        Component={SubstrateCard}
      />
      <Alternative
        id="C+D"
        title="Hybrid · substrate + manifest band  ← combination you picked"
        thesis="Substrate carries the weight; the footer band carries the data and fixes the overlap. Approved tints the paper and adds a hairline band. Booked moves to deeper cream with a soft ink band carrying the serial. Confirmed becomes heavy stock with a full-width inverted ink band — confirmation number engraved across it."
        Component={HybridCard}
      />
    </div>
  );
}

function Alternative({
  id,
  title,
  thesis,
  Component,
}: {
  id: string;
  title: string;
  thesis: string;
  Component: (p: { status: StatusKind }) => ReactNode;
}) {
  return (
    <div className="print:break-inside-avoid">
      <header className="mb-3 flex items-baseline gap-3 print:break-after-avoid">
        <span className="font-mono text-[10px] uppercase tracking-label text-ink/45">
          Alt {id}
        </span>
        <h3 className="font-serif text-xl leading-tight text-ink">{title}</h3>
      </header>
      <p className="mb-4 max-w-3xl text-[12px] leading-relaxed text-ink/70">
        {thesis}
      </p>
      <div className="flex flex-wrap items-end gap-5">
        {STATUSES.map((s) => (
          <div key={s} className="flex flex-col items-center gap-2 print:break-inside-avoid">
            <Component status={s} />
            <p className="text-[10px] uppercase tracking-[0.2em] text-ink/55">
              {s}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- Shared content ---------------------------------------------------

function ExperienceContent({ heavy = false }: { heavy?: boolean }) {
  return (
    <>
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-ink/60">
        <t.Icon size={12} strokeWidth={1.6} aria-hidden />
        <span>{t.label}</span>
      </div>
      <div
        className="mt-2 h-16 w-full overflow-hidden rounded-md border border-ink/10"
        role="img"
        aria-label="Experience hero photo placeholder"
        style={{
          backgroundImage:
            "linear-gradient(135deg, #6a4318 0%, #b58a3a 45%, #ecddbb 100%)",
        }}
      />
      <h3
        className={`mt-2 font-serif leading-snug text-ink ${
          heavy ? "text-[18px]" : "text-[17px]"
        }`}
      >
        Tea ceremony · Urasenke
      </h3>
      <p className="mt-0.5 text-[11px] text-ink/65">Kyoto · 90 min · indoor</p>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip>Reflective</Chip>
        <Chip>Low effort</Chip>
      </div>
    </>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] text-ink/80"
      style={{ backgroundColor: t.tint }}
    >
      {children}
    </span>
  );
}

const baseShellStyle = {
  backgroundImage: `${NOISE_BG}, linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%)`,
  backgroundColor: "#f7f4ee",
};

// ---- Alt A: Wax seal --------------------------------------------------

function WaxSealCard({ status }: { status: StatusKind }) {
  return (
    <div
      role="group"
      aria-label={`Experience card, ${status}`}
      className="relative w-[260px] overflow-hidden rounded-lg border border-ink/10 p-3 font-sans"
      style={{
        ...baseShellStyle,
        boxShadow:
          status === "confirmed"
            ? "0 1px 0 rgba(0,0,0,0.04), 0 14px 32px -10px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.6)"
            : "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
      }}
    >
      <ExperienceContent />
      <div className="absolute -top-1.5 -right-1.5">
        <WaxSeal status={status} />
      </div>
    </div>
  );
}

function WaxSeal({ status }: { status: StatusKind }) {
  if (status === "approved") {
    return (
      <span
        aria-label="Status: approved"
        className="flex h-6 w-6 items-center justify-center rounded-full text-[12px] font-medium"
        style={{
          backgroundColor: "#f7f4ee",
          color: "#0a0a0a",
          boxShadow: "0 0 0 1.5px #0a0a0a, 0 1px 2px rgba(0,0,0,0.15)",
        }}
      >
        ✓
      </span>
    );
  }
  if (status === "booked") {
    return (
      <svg
        width="44"
        height="44"
        viewBox="0 0 44 44"
        role="img"
        aria-label="Status: booked"
        style={{ filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.3))" }}
      >
        <defs>
          <radialGradient id="seal-booked" cx="35%" cy="30%" r="80%">
            <stop offset="0" stopColor="#5a4a3a" />
            <stop offset="1" stopColor="#2a1f15" />
          </radialGradient>
        </defs>
        <circle cx="22" cy="22" r="18" fill="url(#seal-booked)" />
        <circle
          cx="22"
          cy="22"
          r="15"
          fill="none"
          stroke="#a98a4e"
          strokeOpacity="0.6"
          strokeWidth="0.5"
        />
        <text
          x="22"
          y="27"
          textAnchor="middle"
          fontSize="14"
          fill="#d4b876"
          fontFamily="serif"
        >
          ⚿
        </text>
      </svg>
    );
  }
  if (status === "confirmed") {
    const r = 26;
    return (
      <svg
        width="60"
        height="60"
        viewBox="0 0 60 60"
        role="img"
        aria-label="Status: confirmed"
        style={{ filter: "drop-shadow(0 3px 5px rgba(0,0,0,0.4))" }}
      >
        <defs>
          <radialGradient id="seal-conf" cx="35%" cy="28%" r="85%">
            <stop offset="0" stopColor="#6a1a14" />
            <stop offset="0.6" stopColor="#3a0a08" />
            <stop offset="1" stopColor="#1a0303" />
          </radialGradient>
          <path
            id="curve-top"
            d={`M ${30 - r} 30 A ${r} ${r} 0 0 1 ${30 + r} 30`}
            fill="none"
          />
          <path
            id="curve-bot"
            d={`M ${30 - r} 30 A ${r} ${r} 0 0 0 ${30 + r} 30`}
            fill="none"
          />
        </defs>
        <circle cx="30" cy="30" r="27" fill="url(#seal-conf)" />
        <circle
          cx="30"
          cy="30"
          r="22"
          fill="none"
          stroke="#d4b876"
          strokeOpacity="0.55"
          strokeWidth="0.6"
        />
        <text fontSize="5.4" fill="#e6c785" letterSpacing="1.4">
          <textPath href="#curve-top" startOffset="50%" textAnchor="middle">
            CONFIRMED
          </textPath>
        </text>
        <text fontSize="4.2" fill="#d4b876" letterSpacing="0.6">
          <textPath href="#curve-bot" startOffset="50%" textAnchor="middle">
            URASEN-AC-2904
          </textPath>
        </text>
        <text
          x="30"
          y="34"
          textAnchor="middle"
          fontSize="14"
          fill="#e6c785"
          fontFamily="serif"
        >
          ◉
        </text>
      </svg>
    );
  }
  return null;
}

// ---- Alt B: Folded paper corner --------------------------------------

function FoldCornerCard({ status }: { status: StatusKind }) {
  return (
    <div
      role="group"
      aria-label={`Experience card, ${status}`}
      className="relative w-[260px] overflow-hidden rounded-lg border border-ink/10 p-3 font-sans"
      style={{
        ...baseShellStyle,
        boxShadow:
          status === "confirmed"
            ? "0 1px 0 rgba(0,0,0,0.04), 0 14px 32px -10px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.6)"
            : "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
      }}
    >
      <ExperienceContent />
      <FoldCorner status={status} />
    </div>
  );
}

function FoldCorner({ status }: { status: StatusKind }) {
  const cfg =
    status === "approved"
      ? { size: 36, fill: "#c9b585", glyph: "✓", glyphFill: "#3a2a14", serial: null }
      : status === "booked"
      ? { size: 50, fill: "#3a2a1c", glyph: "⚿", glyphFill: "#d4b876", serial: null }
      : status === "confirmed"
      ? {
          size: 64,
          fill: "#1a0a06",
          glyph: "◉",
          glyphFill: "#d4b876",
          serial: "URASEN-AC-2904",
        }
      : null;
  if (!cfg) return null;

  const s = cfg.size;
  return (
    <svg
      width={s}
      height={s}
      viewBox={`0 0 ${s} ${s}`}
      className="absolute right-0 top-0"
      role="img"
      aria-label={`Status: ${status}`}
      style={{ filter: "drop-shadow(-1px 1px 1.5px rgba(0,0,0,0.25))" }}
    >
      <polygon points={`0,0 ${s},0 ${s},${s}`} fill={cfg.fill} />
      <line
        x1="0"
        y1="0"
        x2={s}
        y2={s}
        stroke="rgba(255,255,255,0.18)"
        strokeWidth="0.5"
      />
      <text
        x={s * 0.62}
        y={s * 0.42}
        textAnchor="middle"
        fontSize={s * 0.26}
        fill={cfg.glyphFill}
        fontFamily="serif"
      >
        {cfg.glyph}
      </text>
      {cfg.serial ? (
        <text
          x={s * 0.62}
          y={s * 0.78}
          textAnchor="middle"
          fontSize="5"
          fill={cfg.glyphFill}
          letterSpacing="0.4"
          fontFamily="ui-monospace"
        >
          {cfg.serial}
        </text>
      ) : null}
    </svg>
  );
}

// ---- Alt C: Manifest footer band -------------------------------------

function FooterBandCard({ status }: { status: StatusKind }) {
  return (
    <div
      role="group"
      aria-label={`Experience card, ${status}`}
      className="relative w-[260px] overflow-hidden rounded-lg border border-ink/10 font-sans"
      style={{
        ...baseShellStyle,
        boxShadow:
          status === "confirmed"
            ? "0 1px 0 rgba(0,0,0,0.04), 0 16px 36px -12px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.6)"
            : "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
      }}
    >
      <div className="p-3 pb-0">
        <ExperienceContent />
      </div>
      <FooterBand status={status} />
    </div>
  );
}

function FooterBand({ status }: { status: StatusKind }) {
  if (status === "approved") {
    return (
      <div className="mt-3 flex items-center justify-between border-t border-ink/15 px-3 py-1.5">
        <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-ink/70">
          <span aria-hidden>✓</span> Approved
        </span>
        <span className="font-mono text-[10px] text-ink/45">{STATUS_DATE.approved}</span>
      </div>
    );
  }
  if (status === "booked") {
    return (
      <div
        className="mt-3 flex items-center justify-between px-3 py-2"
        style={{ backgroundColor: "rgba(10,10,10,0.06)" }}
      >
        <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.2em] text-ink/85">
          <span aria-hidden>⚿</span> Booked
        </span>
        <span className="font-mono text-[10px] text-ink/65">{SERIAL.booked}</span>
      </div>
    );
  }
  if (status === "confirmed") {
    return (
      <div
        className="mt-3 flex flex-col px-3 py-2"
        style={{ backgroundColor: "#0a0a0a", color: "#f7f4ee" }}
      >
        <span className="inline-flex items-center gap-2 text-[10px] uppercase tracking-label">
          <span aria-hidden>◉</span> Confirmed
        </span>
        <span className="mt-0.5 font-mono text-[10px] tracking-wide text-paper/75">
          {SERIAL.confirmed}
        </span>
      </div>
    );
  }
  return <div className="h-3" />;
}

// ---- Alt D: Substrate weight -----------------------------------------

function SubstrateCard({ status }: { status: StatusKind }) {
  const cfg = SUBSTRATE_CFG[status];
  return (
    <div
      role="group"
      aria-label={`Experience card, ${status}`}
      className="relative w-[260px] overflow-hidden rounded-lg p-3 font-sans"
      style={{
        backgroundImage: `${NOISE_BG}, linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%)`,
        backgroundColor: cfg.bg,
        border: cfg.border,
        boxShadow: cfg.shadow,
      }}
    >
      <ExperienceContent heavy={status === "confirmed"} />
      {status === "confirmed" ? (
        <div
          className="mt-3 flex items-center justify-between rounded border border-ink/15 px-2 py-1"
          style={{
            backgroundColor: "rgba(10,10,10,0.03)",
            boxShadow:
              "inset 0 1px 0 rgba(255,255,255,0.45), inset 0 -1px 0 rgba(10,10,10,0.10)",
          }}
        >
          <span className="text-[9px] uppercase tracking-[0.32em] text-ink/85">
            Confirmed
          </span>
          <span className="font-mono text-[9px] tracking-wide text-ink/55">
            URASEN-AC-2904
          </span>
        </div>
      ) : status === "booked" ? (
        <div className="mt-2 flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-ink/70">
          <span className="inline-flex items-center gap-1">
            <span aria-hidden>⚿</span> Booked
          </span>
          <span className="font-mono text-[10px] text-ink/45">Mar 12</span>
        </div>
      ) : status === "approved" ? (
        <div className="mt-2 text-right text-[10px] uppercase tracking-[0.2em] text-ink/55">
          <span aria-hidden>✓</span> Approved
        </div>
      ) : null}
    </div>
  );
}

// ---- Alt C+D: Hybrid (chosen direction) ------------------------------

function HybridCard({ status }: { status: StatusKind }) {
  const cfg = HYBRID_CFG[status];
  return (
    <div
      role="group"
      aria-label={`Experience card, ${status}`}
      className="relative w-[260px] overflow-hidden rounded-lg font-sans"
      style={{
        backgroundImage: `${NOISE_BG}, linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%)`,
        backgroundColor: cfg.bg,
        border: cfg.border,
        boxShadow: cfg.shadow,
      }}
    >
      <div className="p-3 pb-0">
        <ExperienceContent heavy={status === "confirmed"} />
      </div>
      <HybridFooter status={status} />
    </div>
  );
}

function HybridFooter({ status }: { status: StatusKind }) {
  if (status === "approved") {
    return (
      <div className="mt-3 flex items-center justify-between border-t border-ink/15 px-3 py-1.5">
        <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-ink/70">
          <span aria-hidden>✓</span> Approved
        </span>
        <span className="font-mono text-[10px] text-ink/45">{STATUS_DATE.approved}</span>
      </div>
    );
  }
  if (status === "booked") {
    return (
      <div
        className="mt-3 flex items-center justify-between px-3 py-2"
        style={{ backgroundColor: "rgba(10,10,10,0.08)" }}
      >
        <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.2em] text-ink/85">
          <span aria-hidden>⚿</span> Booked
        </span>
        <span className="font-mono text-[10px] text-ink/65">{SERIAL.booked}</span>
      </div>
    );
  }
  if (status === "confirmed") {
    return (
      <div
        className="mt-3 flex flex-col px-3 py-2.5"
        style={{ backgroundColor: "#0a0a0a", color: "#f7f4ee" }}
      >
        <div className="flex items-center justify-between">
          <span className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.32em]">
            <span aria-hidden>◉</span> Confirmed
          </span>
          <span className="font-mono text-[9px] tracking-wider text-paper/55">
            {STATUS_DATE.confirmed}
          </span>
        </div>
        <span className="mt-0.5 font-mono text-[10px] tracking-wide text-paper/80">
          {SERIAL.booked}
        </span>
      </div>
    );
  }
  return null;
}

const HYBRID_CFG: Record<
  StatusKind,
  { bg: string; border: string; shadow: string }
> = {
  pending: {
    bg: "#f7f4ee",
    border: "1px solid rgba(10,10,10,0.10)",
    shadow:
      "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
  },
  approved: {
    bg: "#f5f1e7",
    border: "1px solid rgba(10,10,10,0.14)",
    shadow:
      "0 1px 0 rgba(0,0,0,0.05), 0 10px 26px -12px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.55)",
  },
  booked: {
    bg: "#ede6d6",
    border: "1.5px solid rgba(10,10,10,0.20)",
    shadow:
      "0 2px 0 rgba(0,0,0,0.06), 0 14px 32px -10px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.5)",
  },
  confirmed: {
    bg: "#e6dcc4",
    border: "2px solid rgba(10,10,10,0.32)",
    shadow:
      "0 0 0 1px rgba(10,10,10,0.10), 0 3px 0 rgba(0,0,0,0.08), 0 22px 44px -12px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.55)",
  },
  discarded: {
    bg: "#f7f4ee",
    border: "1px solid rgba(10,10,10,0.10)",
    shadow: "0 1px 0 rgba(0,0,0,0.04)",
  },
};

const SUBSTRATE_CFG: Record<
  StatusKind,
  { bg: string; border: string; shadow: string }
> = {
  pending: {
    bg: "#f7f4ee",
    border: "1px solid rgba(10,10,10,0.10)",
    shadow:
      "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
  },
  approved: {
    bg: "#f5f1e7",
    border: "1px solid rgba(10,10,10,0.14)",
    shadow:
      "0 1px 0 rgba(0,0,0,0.05), 0 10px 26px -12px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.55)",
  },
  booked: {
    bg: "#ede6d6",
    border: "1.5px solid rgba(10,10,10,0.20)",
    shadow:
      "0 2px 0 rgba(0,0,0,0.06), 0 14px 32px -10px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.5)",
  },
  confirmed: {
    bg: "#e6dcc4",
    border: "2px solid rgba(10,10,10,0.32)",
    shadow:
      "0 0 0 1px rgba(10,10,10,0.10), 0 3px 0 rgba(0,0,0,0.08), 0 22px 44px -12px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.55), inset 0 0 0 3px rgba(247,244,238,0.7), inset 0 0 0 4px rgba(10,10,10,0.10)",
  },
  discarded: {
    bg: "#f7f4ee",
    border: "1px solid rgba(10,10,10,0.10)",
    shadow: "0 1px 0 rgba(0,0,0,0.04)",
  },
};
