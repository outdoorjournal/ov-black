import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// The OV Black micro-label: uppercase, widely tracked, and dimmed to 60% of
// the *current* text colour so it reads correctly on both the light (ink) and
// dark (paper) surfaces without a tone prop. Pass `rule` to prepend the short
// brand-orange tick used on hero and section eyebrows.
export type EyebrowProps = {
  children: ReactNode;
  rule?: boolean;
  className?: string;
};

export function Eyebrow({ children, rule = false, className }: EyebrowProps) {
  return (
    <span className={cn("flex items-center gap-3", className)}>
      {rule ? <span aria-hidden className="h-px w-8 shrink-0 bg-brand" /> : null}
      <span className="font-sans text-[10px] uppercase tracking-eyebrow opacity-60">
        {children}
      </span>
    </span>
  );
}
