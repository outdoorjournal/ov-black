"use client";

// "Run the AI" buttons. Identical to the vertical's, just defined here so
// the import boundary between prototypes stays narrow.

import { useState } from "react";

interface AIDemoControllerProps {
  onRun: (scenario: "propose" | "assemble" | "modify") => Promise<void>;
  disabled?: boolean;
}

export function AIDemoController({
  onRun,
  disabled = false,
}: AIDemoControllerProps) {
  const [busy, setBusy] = useState<string | null>(null);

  const handle = async (s: "propose" | "assemble" | "modify") => {
    if (busy || disabled) return;
    setBusy(s);
    try {
      await onRun(s);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
        Demo AI
      </span>
      <DemoButton
        label="Propose cards"
        running={busy === "propose"}
        disabled={disabled || busy !== null}
        onClick={() => handle("propose")}
      />
      <DemoButton
        label="Assemble draft"
        running={busy === "assemble"}
        disabled={disabled || busy !== null}
        onClick={() => handle("assemble")}
      />
      <DemoButton
        label="Modify hotel"
        running={busy === "modify"}
        disabled={disabled || busy !== null}
        onClick={() => handle("modify")}
      />
    </div>
  );
}

function DemoButton({
  label,
  running,
  disabled,
  onClick,
}: {
  label: string;
  running: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "rounded-md border px-2.5 py-1 text-[11px] uppercase tracking-[0.16em] transition",
        running
          ? "border-ink/60 bg-ink text-paper"
          : "border-ink/20 bg-paper text-ink/75 hover:bg-ink/5",
        disabled && !running ? "opacity-40" : "",
      ].join(" ")}
    >
      {running ? "…running" : label}
    </button>
  );
}
