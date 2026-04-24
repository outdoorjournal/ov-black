"use client";

export type Viewport = "desktop" | "mobile";

interface ViewportToggleProps {
  viewport: Viewport;
  onChange: (v: Viewport) => void;
}

export function ViewportToggle({ viewport, onChange }: ViewportToggleProps) {
  return (
    <div className="inline-flex rounded-full border border-ink/15 bg-paper p-0.5">
      <ToggleButton
        active={viewport === "desktop"}
        onClick={() => onChange("desktop")}
      >
        Desktop
      </ToggleButton>
      <ToggleButton
        active={viewport === "mobile"}
        onClick={() => onChange("mobile")}
      >
        Mobile
      </ToggleButton>
    </div>
  );
}

function ToggleButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.22em] transition",
        active ? "bg-ink text-paper" : "text-ink/60 hover:text-ink",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
