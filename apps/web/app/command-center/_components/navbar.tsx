"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { signOutAction } from "../_actions/sign-out";

type NavbarProps = {
  email: string;
};

type NavItem = {
  label: string;
  href: string;
  // True when the current pathname should light up this entry. Kept as a
  // predicate rather than a flat string so nested routes (e.g. a future
  // /clients/[id] detail) still highlight their parent tab.
  isActive: (pathname: string) => boolean;
};

const NAV: readonly NavItem[] = [
  {
    label: "Overview",
    href: "/command-center",
    isActive: (p) => p === "/command-center",
  },
  {
    label: "Clients",
    href: "/command-center/clients",
    isActive: (p) =>
      p.startsWith("/command-center/clients") ||
      p.startsWith("/command-center/new-client"),
  },
];

/**
 * Editorial top bar for advisor-facing pages. The brand wordmark matches
 * the landing page header exactly — same serif, same uppercase "Black"
 * eyebrow — so the transition between sign-in and authed surfaces feels
 * like the same publication.
 *
 * A quiet secondary row carries the advisor's primary navigation. We keep
 * it on the same ink background so the nav reads as part of the masthead
 * rather than a separate toolbar, and use a hairline underline to mark
 * the active tab in the brand style.
 *
 * Sign-out is a plain <form> posting to a server action so there is no
 * client-side auth SDK call and the session cookies are cleared on the
 * same response that redirects away.
 */
export function Navbar({ email }: NavbarProps) {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 z-40 border-b border-paper/10 bg-ink text-paper">
      <div className="flex items-center justify-between gap-6 px-6 py-4 sm:px-10">
        <Link
          href="/command-center"
          className="flex items-baseline gap-3 transition-opacity hover:opacity-80"
        >
          <span className="font-serif text-xl tracking-tight">
            Outdoor Voyage
          </span>
          <span className="text-[10px] uppercase tracking-[0.35em] text-paper/60">
            Black
          </span>
        </Link>

        <div className="flex items-center gap-6">
          <span
            className="hidden max-w-[18rem] truncate text-xs text-paper/70 sm:inline"
            title={email}
          >
            {email}
          </span>
          <form action={signOutAction}>
            <button
              type="submit"
              className="rounded-none border-b border-transparent text-[10px] uppercase tracking-[0.3em] text-paper/70 transition-colors hover:border-paper/70 hover:text-paper"
            >
              Sign out
            </button>
          </form>
        </div>
      </div>

      <div className="border-t border-paper/10">
        <div className="flex items-center gap-8 px-6 sm:px-10">
          {NAV.map((item) => {
            const active = item.isActive(pathname ?? "");
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={
                  "relative py-3 font-sans text-[10px] uppercase tracking-[0.3em] transition-colors " +
                  (active
                    ? "text-paper"
                    : "text-paper/55 hover:text-paper")
                }
              >
                {item.label}
                {active ? (
                  <span
                    aria-hidden
                    className="absolute inset-x-0 bottom-0 h-px bg-paper"
                  />
                ) : null}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
