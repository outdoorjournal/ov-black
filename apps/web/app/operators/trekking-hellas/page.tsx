// Operator profile — /operators/trekking-hellas.
//
// A public, on-brand dossier for a single vetted operator. The concept: rather
// than presenting inventory as anonymous line items, we stand behind the people
// who run it. This page tells the traveler who Trekking Hellas is, why we chose
// them, and what our vetting actually means — using the operator's own imagery
// and marks, framed in OV Black's editorial chrome (shared SiteHeader/Footer).
//
// Static content today; a later slice can lift the operator record out of the
// inventory graph and drive these fields from data.

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import { Eyebrow } from "@/components/ui/eyebrow";
import { Button } from "@/components/ui/button";
import { SiteHeader } from "@/app/_components/marketing/SiteHeader";
import { SiteFooter } from "@/app/_components/marketing/SiteFooter";

const ASSET = "/operators/trekking-hellas";

export const metadata: Metadata = {
  title: "Trekking Hellas · A vetted operator — Outdoor Voyage Black",
  description:
    "Forty years on the ground in Greece. Trekking Hellas is a Travelife- and ATTA-accredited operator, journalistically vetted by Outdoor Voyage so your money reaches the guides who earn it.",
};

// ── Facts, drawn from the operator's own record ──────────────────────────────
const STATS: { value: string; label: string }[] = [
  { value: "40", label: "Years on the ground" },
  { value: "24", label: "Local offices across Greece" },
  { value: "40+", label: "Ways to move through a landscape" },
  { value: "8", label: "Greek regions, plus six continents" },
];

// What the OV vetting standard actually checks — sourced from the Outdoor
// Voyage business model: certified & insured, ethical, money to communities.
const VETTING: { title: string; body: string }[] = [
  {
    title: "Certified & insured",
    body: "Licensed by the Greek National Tourism Organisation (MHTE 0259E60000534501) and fully insured — verified before a single trip reaches you.",
  },
  {
    title: "Journalistically vetted",
    body: "Assessed with the same deep, on-the-ground scrutiny we built at The Outdoor Journal — not a directory listing, but people we have actually stood beside.",
  },
  {
    title: "Money reaches the ground",
    body: "We cut out the middlemen who quietly retain 40–60% of what travelers spend. You pay the operator directly; the value stays with the guides and their communities.",
  },
];

const CREDENTIALS: { src: string; alt: string; w: number; h: number }[] = [
  { src: `${ASSET}/badge-travelife.png`, alt: "Travelife Partner", w: 2127, h: 827 },
  { src: `${ASSET}/badge-atta.png`, alt: "Adventure Travel Trade Association member", w: 500, h: 145 },
  { src: `${ASSET}/badge-discover-greece.png`, alt: "Discover Greece proud partner", w: 842, h: 842 },
  { src: `${ASSET}/badge-metron.png`, alt: "Metron Sustainable Tourism 2024", w: 4500, h: 4500 },
  { src: `${ASSET}/badge-ecoe.jpg`, alt: "European Outdoor Group (EC-OE) member", w: 1397, h: 1715 },
];

export default function TrekkingHellasPage() {
  return (
    <main className="bg-paper text-ink">
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative isolate overflow-hidden bg-ink text-paper">
        <Image
          src={`${ASSET}/hero-1.jpg`}
          alt="A guided ascent above the clouds in the Greek mountains"
          fill
          priority
          sizes="100vw"
          className="object-cover object-center opacity-70"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-b from-ink/70 via-ink/40 to-ink"
        />

        <div className="relative z-10 flex min-h-[92vh] flex-col">
          <SiteHeader />

          <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col justify-end gap-8 px-6 pb-20 sm:px-10">
            <div className="flex items-center gap-4">
              <span className="inline-flex items-center rounded-sm bg-paper px-4 py-3 shadow-float">
                <Image
                  src={`${ASSET}/logo-header.svg`}
                  alt="Trekking Hellas"
                  width={150}
                  height={58}
                  className="h-11 w-auto"
                />
              </span>
              <Eyebrow rule className="text-paper">
                Vetted operator · Greece
              </Eyebrow>
            </div>

            <h1 className="max-w-3xl font-serif text-5xl leading-[1.03] tracking-tight sm:text-6xl lg:text-7xl">
              Forty years of Greece, on foot.
            </h1>
            <p className="max-w-xl text-base leading-relaxed text-paper/80 sm:text-lg">
              From the summit of Olympus to the sea caves of the Aegean, Trekking
              Hellas has been the standard for Greek adventure since 1985. We
              vetted them so you don&rsquo;t have to — and we&rsquo;re proud to
              build your voyage on their shoulders.
            </p>

            <div className="flex flex-wrap items-center gap-4 pt-2">
              <Button asChild variant="brand" size="lg">
                <Link href="/">Request an introduction</Link>
              </Button>
              <a
                href="#vetting"
                className="text-[11px] uppercase tracking-label text-paper/70 transition-colors hover:text-paper"
              >
                How we vet →
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stat band ────────────────────────────────────────────────────── */}
      <section className="border-b border-ink/10 bg-paper">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-8 px-6 py-14 sm:px-10 lg:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label} className="flex flex-col gap-2">
              <span className="font-serif text-5xl leading-none tracking-tight">
                {s.value}
              </span>
              <span className="text-[11px] uppercase tracking-label text-ink/55">
                {s.label}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ── The operator, in their own words ─────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-24 sm:px-10">
        <div className="grid gap-16 lg:grid-cols-2 lg:items-center lg:gap-20">
          <div>
            <Eyebrow rule>Who they are</Eyebrow>
            <h2 className="mt-6 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">
              The people who wrote the map.
            </h2>
            <div className="mt-6 space-y-5 text-base leading-relaxed text-ink/75">
              <p>
                Founded in Athens in 1985, Trekking Hellas turned Greek outdoor
                adventure from a pastime into a craft. Four decades on, they run
                <span className="text-ink"> 24 local offices</span> the length of
                the country — from Epirus and the Zagori stone villages to the
                Peloponnese, Thessaly, and the islands.
              </p>
              <p>
                Their guides move you through the land in more than forty ways:
                hiking and mountaineering, sea kayaking and rafting, canyoning,
                cycling, gastronomy, and family expeditions. What binds it is a
                conviction we share — that the outdoors is a way of life, not a
                transaction, and that travel should leave the place better than
                it found it.
              </p>
              <p>
                They visit in the shoulder seasons, keep the footprint light,
                and route spend back into the communities that host you. It is
                exactly the ethic that earns a place in Outdoor Voyage Black.
              </p>
            </div>
          </div>

          <div className="relative aspect-[4/5] overflow-hidden rounded-sm shadow-float">
            <Image
              src={`${ASSET}/hero-2.jpg`}
              alt="Trekking Hellas guides on a Greek mountain trail"
              fill
              sizes="(min-width: 1024px) 40vw, 100vw"
              className="object-cover"
            />
          </div>
        </div>
      </section>

      {/* ── Why we stand behind them (the OV vetting standard) ───────────── */}
      <section id="vetting" className="bg-ink text-paper">
        <div className="mx-auto max-w-6xl px-6 py-24 sm:px-10">
          <div className="max-w-2xl">
            <Eyebrow rule className="text-paper">
              Why we present them
            </Eyebrow>
            <h2 className="mt-6 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">
              Vetted, not merely listed.
            </h2>
            <p className="mt-6 text-base leading-relaxed text-paper/70">
              Anyone can resell a trip. Outdoor Voyage exists to do the harder
              thing — to know the operator, guarantee the standard, and make sure
              the money lands where the work is done.
            </p>
          </div>

          <div className="mt-14 grid gap-px overflow-hidden rounded-sm border border-paper/10 bg-paper/10 sm:grid-cols-3">
            {VETTING.map((v) => (
              <div key={v.title} className="bg-ink p-8">
                <h3 className="font-serif text-2xl tracking-tight">{v.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-paper/70">
                  {v.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Credentials ──────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-24 sm:px-10">
        <div className="flex flex-col gap-3">
          <Eyebrow rule>The receipts</Eyebrow>
          <h2 className="font-serif text-4xl tracking-tight sm:text-5xl">
            Accredited where it counts.
          </h2>
          <p className="max-w-2xl text-base leading-relaxed text-ink/65">
            Independent memberships and sustainability marks we verified as part
            of onboarding Trekking Hellas.
          </p>
        </div>

        <div className="mt-12 flex flex-wrap items-center gap-x-14 gap-y-10">
          {CREDENTIALS.map((c) => (
            <Image
              key={c.src}
              src={c.src}
              alt={c.alt}
              width={c.w}
              height={c.h}
              className="h-14 w-auto object-contain opacity-80 transition-opacity hover:opacity-100"
            />
          ))}
        </div>

        <p className="mt-12 text-[11px] uppercase tracking-label text-ink/45">
          Licences — MHTE 0259E60000534501 · GECR 000137043701000
        </p>
      </section>

      {/* ── Closing invitation over a full-bleed frame ───────────────────── */}
      <section className="relative isolate overflow-hidden bg-ink text-paper">
        <Image
          src={`${ASSET}/hero-3.jpg`}
          alt="Aerial view of the Greek coastline"
          fill
          sizes="100vw"
          className="object-cover opacity-55"
        />
        <div aria-hidden className="absolute inset-0 bg-ink/55" />
        <div className="relative z-10 mx-auto flex max-w-3xl flex-col items-center gap-8 px-6 py-28 text-center sm:px-10">
          <Eyebrow className="text-paper">Outdoor Voyage · Black</Eyebrow>
          <h2 className="font-serif text-4xl leading-tight tracking-tight sm:text-5xl">
            Let&rsquo;s build your Greece with them.
          </h2>
          <p className="max-w-xl text-base leading-relaxed text-paper/80">
            Your concierge will shape an itinerary with Trekking Hellas&rsquo;
            guides — bespoke, unhurried, and entirely yours. Membership is by
            referral only.
          </p>
          <Button asChild variant="brand" size="lg">
            <Link href="/">Request an introduction</Link>
          </Button>
        </div>
      </section>

      <SiteFooter />
    </main>
  );
}
