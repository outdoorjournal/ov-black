"use client";

// Sticky in-page navigation for the client workspace (Wave F). Anchor links
// over the recomposed sections with an IntersectionObserver scroll-spy — the
// active section gets a paper underline (never orange; location is not
// urgency). Purely presentational: the sections themselves are server-rendered.

import { useEffect, useState } from "react";

export type SubNavSection = { id: string; label: string };

export function ClientSubNav({ sections }: { sections: SubNavSection[] }) {
  const [active, setActive] = useState<string | null>(sections[0]?.id ?? null);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        // Track the section crossing the upper reading band; the last
        // intersecting entry in document order wins on fast scrolls.
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id);
        }
      },
      { rootMargin: "-15% 0px -75% 0px" },
    );
    for (const section of sections) {
      const el = document.getElementById(section.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [sections]);

  return (
    <nav
      aria-label="Client sections"
      className="sticky top-0 z-30 -mx-1 border-b border-paper/10 bg-ink/95 px-1 backdrop-blur"
    >
      <ul className="flex gap-1 overflow-x-auto">
        {sections.map((section) => {
          const isActive = section.id === active;
          return (
            <li key={section.id}>
              <a
                href={`#${section.id}`}
                aria-current={isActive ? "location" : undefined}
                className={`inline-block whitespace-nowrap border-b-2 px-3 py-2.5 font-sans text-xs uppercase tracking-label transition-colors ${
                  isActive
                    ? "border-paper text-paper"
                    : "border-transparent text-paper/50 hover:text-paper"
                }`}
              >
                {section.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
