// Demo campaign entry point — a magazine-style article page that stands in for
// the Backpacker Mt Olympus piece referenced by the olympus campaign's reading
// list (see apps/api/app/campaigns/registry.py). The editorial copy here is
// original demo content, not the published article. Its one job: read like a
// destination story, then funnel the signed-in traveler into /campaign/olympus
// via the sponsored CTA.

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Mt. Olympus: Hiking Up the Mountain of the Gods — Backpacker",
  description:
    "The classic two-day ascent from Litochoro to the Mytikas summit — refuges, the ridgeline scramble, and how to plan it.",
};

const HERO_IMAGE =
  "https://cdn-pub.prod.outdoorvoyage.com/operators/018f395d-288e-777c-a64d-3808a193b686/trips/018f39f5-7050-7b2c-a1c4-0c689797f113/images/xVMqslnvADKj.jpg";

// Chrome palette matched to the live backpacker.com (Outside-network era):
// dark-green brand bar, yellow Join Now / active-nav underline.
const BRAND_GREEN = "#325d55";
const BRAND_YELLOW = "#ffd800";

const NAV_ITEMS = [
  "Home",
  "Featured",
  "Deals",
  "Gear",
  "Trips",
  "Skills",
  "Survival",
  "News & Events",
  "Videos",
  "Stories",
];

const FOOTER_INSPIRATION_A = [
  "Backpacker",
  "Clean Eating",
  "Climbing",
  "Outside",
  "Outside Learn",
  "Outside TV",
  "Pinkbike",
  "RUN",
];
const FOOTER_INSPIRATION_B = [
  "SKI",
  "Triathlete",
  "Velo",
  "National Park Trips",
  "Warren Miller",
  "Yoga Journal",
  "Podcasts",
  "Scout",
];
const FOOTER_MAPPING = [
  "Gaia GPS",
  "Trailforks",
  "MapMyFitness",
  "MapMyRide",
  "MapMyRun",
  "MapMyWalk",
];
const FOOTER_DEALS = [
  "Outside Online Deals",
  "Yoga Journal Deals",
  "RUN Deals",
  "Velo Deals",
  "Backpacker Deals",
  "Tri Deals",
  "Climbing Deals",
  "Ski Deals",
  "Pinkbike Deals",
];

function FooterColumn({ title, links }: { title?: string; links: string[] }) {
  return (
    <div>
      <p className="text-lg font-bold text-neutral-900">
        {title ?? " "}
      </p>
      <ul className="mt-5 space-y-4">
        {links.map((l) => (
          <li key={l}>
            <span className="cursor-pointer text-[15px] text-neutral-800 hover:underline">
              {l}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CampaignCta({ variant }: { variant: "inline" | "footer" }) {
  const isFooter = variant === "footer";
  return (
    <aside
      className={
        isFooter
          ? "my-12 overflow-hidden rounded-lg"
          : "my-10 overflow-hidden rounded-lg border border-neutral-200"
      }
      style={isFooter ? { backgroundColor: "#1c1913" } : undefined}
    >
      <div className={isFooter ? "px-8 py-10 text-center" : "px-6 py-6"}>
        <p
          className={`text-[11px] font-semibold uppercase tracking-[0.25em] ${
            isFooter ? "text-[#c69a54]" : "text-neutral-400"
          }`}
        >
          Presented by Outdoor Voyage
        </p>
        <h3
          className={`mt-2 font-serif ${
            isFooter
              ? "text-3xl leading-snug text-[#e8dcc4]"
              : "text-xl leading-snug text-neutral-900"
          }`}
        >
          Ready to stand on the roof of Greece?
        </h3>
        <p
          className={`mt-2 text-sm leading-relaxed ${
            isFooter ? "mx-auto max-w-md text-[#e8dcc4]/80" : "text-neutral-600"
          }`}
        >
          Outdoor Voyage builds guided Olympus ascents around you — Litochoro to
          the summit ridge, refuges booked, every day shaped to your pace.
        </p>
        <Link
          href="/campaign/olympus"
          className={`mt-4 inline-block rounded-full px-7 py-2.5 text-[15px] font-bold transition-opacity hover:opacity-90 ${
            isFooter ? "text-neutral-900" : "text-white"
          }`}
          style={{
            backgroundColor: isFooter ? BRAND_YELLOW : BRAND_GREEN,
          }}
        >
          Begin your ascent
        </Link>
      </div>
    </aside>
  );
}

export default function MtOlympusArticlePage() {
  return (
    <div className="min-h-dvh bg-white text-neutral-900">
      {/* Masthead — two green bars, matching the live site's fixed header. */}
      <header
        className="sticky top-0 z-50 text-white shadow-md"
        style={{ backgroundColor: BRAND_GREEN }}
      >
        {/* Row 1: hamburger + Newsletters | centered wordmark | Sign In / Join Now */}
        <div className="relative flex h-[68px] items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-5">
            <button
              type="button"
              aria-label="Menu"
              className="flex flex-col gap-[5px]"
            >
              <span className="h-[3px] w-7 rounded bg-white" />
              <span className="h-[3px] w-7 rounded bg-white" />
              <span className="h-[3px] w-7 rounded bg-white" />
            </button>
            <button
              type="button"
              className="hidden items-center gap-2 rounded-full border-2 border-white px-5 py-2 text-[15px] font-semibold md:flex"
            >
              <svg
                aria-hidden
                viewBox="0 0 24 24"
                className="h-4 w-5 fill-none stroke-white stroke-2"
              >
                <rect x="2" y="4" width="20" height="16" rx="2" />
                <path d="m2 6 10 7L22 6" />
              </svg>
              Newsletters
            </button>
          </div>

          <div className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center">
            <img
              src="https://cdn.backpacker.com/wp-content/themes/backpacker-child/resources/assets/images/logo.svg"
              alt="Backpacker Magazine logo"
              className="h-[26px] w-[120px] sm:w-[200px]"
            />
            <p className="mt-1 text-[11px] leading-none">
              Powered by <span className="font-bold">Outside</span>
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              className="hidden rounded-full border-2 border-white px-5 py-2 text-[15px] font-semibold sm:block"
            >
              Sign In
            </button>
            <button
              type="button"
              className="rounded-full px-5 py-2 text-[15px] font-bold text-neutral-900"
              style={{ backgroundColor: BRAND_YELLOW }}
            >
              Join Now
            </button>
          </div>
        </div>

        {/* Row 2: section nav, active section underlined in yellow */}
        <nav className="flex w-full items-center justify-center gap-7 px-4 pb-3 pt-1 text-[16px] font-semibold">
          {NAV_ITEMS.map((item) => (
            <span
              key={item}
              className={`cursor-pointer whitespace-nowrap ${
                item === "Trips" ? "border-b-[3px] pb-1" : "hidden lg:inline"
              }`}
              style={
                item === "Trips" ? { borderColor: BRAND_YELLOW } : undefined
              }
            >
              {item}
            </span>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-3xl px-6 pb-20">
        {/* Kicker / breadcrumb */}
        <p className="pt-10 text-[15px] font-medium">
          <span className="cursor-pointer" style={{ color: BRAND_GREEN }}>
            Trips
          </span>
          <span className="mx-2 text-neutral-400">&gt;</span>
          <span className="cursor-pointer" style={{ color: BRAND_GREEN }}>
            Adventure Travel
          </span>
        </p>

        <h1 className="mt-4 text-4xl font-black leading-tight tracking-tight sm:text-5xl">
          Mt. Olympus: Hiking Up the Mountain of the Gods
        </h1>
        <p className="mt-4 text-lg leading-relaxed text-neutral-600">
          Greece&apos;s highest peak is a two-day walk from a seaside town — a
          gorge, a stone refuge above the clouds, and a final scramble to the
          throne of Zeus. Here&apos;s how the classic ascent unfolds.
        </p>

        <div className="mt-6 flex items-center gap-3 border-y border-neutral-200 py-3 text-sm text-neutral-500">
          <span className="font-semibold text-neutral-800">
            By Marissa Kalos
          </span>
          <span aria-hidden>·</span>
          <span>9 min read</span>
        </div>

        {/* Hero */}
        <figure className="mt-8">
          <img
            src={HERO_IMAGE}
            alt="The summit ridge of Mount Olympus above a sea of clouds"
            className="aspect-[3/2] w-full rounded-md object-cover"
          />
          <figcaption className="mt-2 text-xs text-neutral-400">
            The Mytikas summit ridge, 9,573 feet above the Aegean.
          </figcaption>
        </figure>

        {/* Body */}
        <article className="prose-lg mt-10 space-y-6 font-serif leading-relaxed text-neutral-800">
          <p>
            From the square in Litochoro you can see the whole problem at once.
            The town sits nearly at sea level, close enough to the Aegean to
            smell it, and behind the last row of rooftops the ground simply
            leaves — nine and a half thousand feet of limestone stacked into
            haze. The Greeks put their gods up there for a reason. It looks
            unreachable. It isn&apos;t, quite.
          </p>
          <p>
            Most hikers take two days. Drive or cab the winding road to Prionia,
            the trailhead at about 3,600 feet, where the pavement ends at a
            taverna and a spring. From there the E4 path climbs steadily through
            beech and black pine, switchbacking out of the Enipeas valley. In
            about three hours you reach Spilios Agapitos — &ldquo;Refuge
            A&rdquo; to everyone on the mountain — a stone lodge at 6,900 feet
            with bunks, hot food, and a terrace that hangs over the whole
            Thermaic Gulf. Book ahead in summer. Watching the lights of the
            coast come on from that terrace is half the reason to come.
          </p>
          <p>
            Summit day starts before dawn. Above the refuge the trees quit, the
            trail turns to scree, and the ridge resolves into individual
            summits: Skala first, then the real prize. From Skala the route to
            Mytikas — at 9,573 feet the highest point in Greece — drops into
            the notorious Kaki Skala, the &ldquo;evil staircase,&rdquo; a
            few hundred feet of exposed Class 3 scrambling on ledges above a
            very long view. It is easier than it looks and more serious than it
            feels: helmets are smart, and in wind or storm you simply
            don&apos;t go. Those who&apos;d rather keep hands in pockets can
            traverse instead to Skolio, the second summit, twenty feet lower
            and a walk-up, with the best view on the massif of Stefani —
            the &ldquo;Throne of Zeus&rdquo; — rearing next door.
          </p>
          <p>
            There&apos;s a quieter way down, and it may be the best part.
            Descend east onto the Plateau of the Muses, a hanging meadow at
            8,500 feet where the Kakkalos refuge sits alone under Stefani&apos;s
            north wall. Spend a second night there if you can, then drop the
            long ridge to Petrostrouga and down to the Gortsia trailhead —
            or retrace to Prionia and walk the Enipeas gorge the whole way home
            to Litochoro, past monasteries and swimming holes the color of
            glacier milk.
          </p>

          <CampaignCta variant="inline" />

          <p>
            The season is short and sweet: mid-June through September, once the
            snow leaves the couloirs and before it returns. Afternoon
            thunderstorms build fast off the sea in high summer, which is the
            other argument for the pre-dawn start. Carry layers you&apos;d
            trust at 9,000 feet in any range — the Mediterranean below does
            not reach the ridge — and two liters of water from the refuge,
            because the upper mountain is dry.
          </p>
          <p>
            None of it requires ropes, or permits, or anything more exotic than
            a reservation and a weather window. That&apos;s the strange gift of
            Olympus: the most storied mountain in the Western imagination is
            also one of its most walkable. You leave a beach town after
            breakfast, and by the next morning you&apos;re picking your way
            along the spine of mythology with the whole Aegean silvering below.
            The gods chose well.
          </p>
        </article>

        <CampaignCta variant="footer" />
      </main>

      {/* Site footer — the Outside-network footer, matching the live site. */}
      <footer className="border-t border-neutral-200 bg-white">
        {/* Outside wordmark + Advertise pill */}
        <div className="mx-auto flex max-w-7xl items-center justify-between border-b border-neutral-200 px-6 py-8">
          <span className="font-serif text-4xl font-black tracking-tight text-neutral-900">
            Outside
          </span>
          <button
            type="button"
            className="rounded-full bg-neutral-900 px-6 py-3 text-[15px] font-bold text-white"
          >
            Advertise With Us
          </button>
        </div>

        {/* Link columns | Join Now panel */}
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-x-10 gap-y-12 px-6 py-12 md:grid-cols-[1fr_1fr_1fr_1fr_minmax(280px,1.4fr)]">
          <FooterColumn title="Inspiration" links={FOOTER_INSPIRATION_A} />
          <div className="pt-[44px] md:pt-0">
            <FooterColumn links={FOOTER_INSPIRATION_B} />
          </div>
          <FooterColumn title="Mapping" links={FOOTER_MAPPING} />
          <FooterColumn title="Deals" links={FOOTER_DEALS} />
          <div className="col-span-2 border-t border-neutral-200 pt-10 text-center md:col-span-1 md:border-l md:border-t-0 md:pl-10 md:pt-0">
            <p className="text-lg font-bold text-neutral-900">Join Now</p>
            <p className="mx-auto mt-4 max-w-xs text-[15px] leading-relaxed text-neutral-800">
              Get inspired with adventure reads, dream up your next trip with
              travel advice, and navigate offline with Gaia GPS Premium.
            </p>
            <div className="mx-auto mt-8 flex max-w-[280px] flex-col gap-4">
              <Link
                href="/campaign/olympus"
                className="rounded-full py-3 text-[15px] font-bold text-neutral-900"
                style={{ backgroundColor: BRAND_YELLOW }}
              >
                Join Now
              </Link>
              <button
                type="button"
                className="rounded-full border-2 border-neutral-900 py-3 text-[15px] font-bold text-neutral-900"
              >
                Sign In
              </button>
            </div>
          </div>
        </div>

        {/* Legal strip */}
        <div className="mx-auto max-w-7xl border-t border-neutral-200 px-6 py-8 text-[14px] text-neutral-800">
          <div className="flex flex-wrap gap-x-6 gap-y-2 font-medium">
            <span className="cursor-pointer hover:underline">Contact</span>
            <span className="cursor-pointer hover:underline">Careers</span>
            <span className="cursor-pointer hover:underline">
              Gear Up Give Back
            </span>
            <span className="cursor-pointer hover:underline">
              Licensing &amp; Accolades
            </span>
          </div>
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
            <span>© 2026 Outside Interactive, Inc.</span>
            <span className="cursor-pointer hover:underline">Terms of Use</span>
            <span className="cursor-pointer hover:underline">
              Privacy Policy
            </span>
          </div>
          <p className="mt-4 cursor-pointer hover:underline">
            WA Privacy Notice
          </p>
          <p className="mt-8 text-center text-[11px] text-neutral-300">
            Demo reproduction for the Outdoor Voyage prototype — not affiliated
            with Backpacker or Outside Inc.
          </p>
        </div>
      </footer>
    </div>
  );
}
