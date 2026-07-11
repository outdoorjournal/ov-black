"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState, useTransition } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import type {
  ClientContactCreate,
  ClientCreatePayload,
  ContactKind,
  DossierFactCreate,
  OsintFactCreate,
  ProfileFactCreate,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { createClientAction } from "../actions";

// Onboarding form. The typed core (children ages, contact preference,
// notes, net worth) lands on the Dossier row; the optional fact seeds
// land on dossier_facts / profile_facts / osint_facts so the advisor can
// front-load knowledge in one round-trip. The detail-page Add forms reuse
// the same shapes for ongoing edits — no parallel UI.

const CONTACT_CHANNELS = ["email", "sms", "whatsapp", "phone"] as const;

const CONTACT_KINDS: ContactKind[] = [
  "phone_cell",
  "phone_home",
  "phone_work",
  "whatsapp",
  "signal",
  "telegram",
  "imessage",
  "instagram",
  "linkedin",
  "x",
  "facebook",
  "wechat",
  "other",
];

const CONTACT_KIND_LABELS: Record<ContactKind, string> = {
  phone_cell: "Cell",
  phone_home: "Home",
  phone_work: "Work",
  whatsapp: "WhatsApp",
  signal: "Signal",
  telegram: "Telegram",
  imessage: "iMessage",
  instagram: "Instagram",
  linkedin: "LinkedIn",
  x: "X",
  facebook: "Facebook",
  wechat: "WeChat",
  other: "Other",
};

const TIERS = ["dossier", "profile", "osint"] as const;
type Tier = (typeof TIERS)[number];

const TIER_LABELS: Record<Tier, string> = {
  dossier: "Dossier",
  profile: "Profile",
  osint: "OSINT",
};

const KIND_LABELS: Record<string, string> = {
  passion: "Passion",
  motivation: "Motivation",
  travel_history: "Travel History",
  trigger: "Trigger",
  constraint: "Constraint",
  deal_breaker: "Deal Breaker",
  dream_signal: "Dream Signal",
  preference: "Preference",
  aspiration: "Aspiration",
  medical: "Medical",
  party: "Party",
  other: "Other",
  linkedin: "LinkedIn",
  facebook: "Facebook",
  instagram: "Instagram",
  press: "Press",
  company: "Company",
  public_record: "Public Record",
};

const KIND_OPTIONS: Record<Tier, readonly string[]> = {
  dossier: [
    "passion",
    "motivation",
    "travel_history",
    "trigger",
    "constraint",
    "deal_breaker",
    "dream_signal",
    "preference",
    "party",
    "other",
  ],
  profile: [
    "passion",
    "motivation",
    "travel_history",
    "trigger",
    "constraint",
    "deal_breaker",
    "dream_signal",
    "preference",
    "aspiration",
    "medical",
    "other",
  ],
  osint: [
    "linkedin",
    "facebook",
    "instagram",
    "press",
    "company",
    "public_record",
    "other",
  ],
};

const TIER_RULES: Record<Tier, string> = {
  dossier: "Private — never shown to traveler.",
  profile: "Traveler self-expression — agent may reference.",
  osint: "External research — never reveal or allude to.",
};

const DEFAULT_KIND: Record<Tier, string> = {
  dossier: "passion",
  profile: "preference",
  osint: "linkedin",
};

// Dark ops-shell field styling. The base Input/Select/Textarea primitives are
// tuned for the light client surfaces (cream bg, ink text); on the ink
// Command Center frame they need transparent fills + paper text, matching the
// detail-page Add forms (AddDossierFactForm et al.).
const FIELD_DARK =
  "border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30";

const factSchema = z.object({
  tier: z.enum(TIERS),
  kind: z.string().min(1),
  text: z.string().trim().max(4000).default(""),
  url: z.string().trim().max(2000).default(""),
});

const contactSchema = z.object({
  kind: z.enum(CONTACT_KINDS as [ContactKind, ...ContactKind[]]),
  value: z.string().trim().max(256).default(""),
  label: z.string().trim().max(64).default(""),
});

const formSchema = z.object({
  full_name: z.string().trim().min(1, "Required").max(200),
  email: z.string().trim().email("Enter a valid email"),
  contact_preference: z.enum(CONTACT_CHANNELS),
  children_ages_raw: z.string().trim().max(200).default(""),
  travel_party_notes: z.string().trim().max(2000).default(""),
  estimated_net_worth_usd: z.string().trim().max(32).default(""),
  contacts: z.array(contactSchema).default([]),
  facts: z.array(factSchema).default([]),
  // When true (default) the create emails a welcome sign-in link now; when
  // false the client is stood up silently to build for first — invite later.
  notify: z.boolean().default(true),
});

type FormInput = z.input<typeof formSchema>;
type FormValues = z.output<typeof formSchema>;

const DEFAULT_VALUES: FormInput = {
  full_name: "",
  email: "",
  contact_preference: "email",
  children_ages_raw: "",
  travel_party_notes: "",
  estimated_net_worth_usd: "",
  contacts: [],
  facts: [],
  notify: true,
};

function parseAges(raw: string): number[] {
  if (!raw) return [];
  return raw
    .split(/[\s,]+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => Number.parseInt(t, 10))
    .filter((n) => Number.isFinite(n) && n >= 0 && n <= 25);
}

function toPayload(values: FormValues): ClientCreatePayload {
  const ages = parseAges(values.children_ages_raw);
  // Tolerate human-formatted entries like "$250,000,000" or "250 000 000".
  // parseInt stops at the first non-digit, so "250,000,000" → 250 silently —
  // strip everything that isn't a digit before parsing.
  const netWorthDigits = values.estimated_net_worth_usd.replace(/[^\d]/g, "");
  const netWorthParsed = netWorthDigits
    ? Number.parseInt(netWorthDigits, 10)
    : NaN;

  const dossier_facts: DossierFactCreate[] = [];
  const profile_facts: ProfileFactCreate[] = [];
  const osint_facts: OsintFactCreate[] = [];
  const contacts: ClientContactCreate[] = [];

  for (const c of values.contacts) {
    const value = c.value.trim();
    if (!value) continue;
    contacts.push({
      kind: c.kind,
      value,
      label: c.label.trim(),
    });
  }

  for (const f of values.facts) {
    const text = f.text.trim();
    if (!text) continue;
    if (f.tier === "dossier") {
      dossier_facts.push({
        kind: f.kind as DossierFactCreate["kind"],
        text,
        source_kind: "advisor",
        source_ref: {},
        observed_at: null,
      });
    } else if (f.tier === "profile") {
      profile_facts.push({
        kind: f.kind as ProfileFactCreate["kind"],
        text,
        source_kind: "advisor",
        source_ref: {},
        observed_at: null,
      });
    } else {
      const sourceRef: Record<string, unknown> = {};
      const url = f.url.trim();
      if (url) sourceRef["url"] = url;
      osint_facts.push({
        kind: f.kind as OsintFactCreate["kind"],
        text,
        source_kind: "advisor",
        source_ref: sourceRef,
        observed_at: null,
      });
    }
  }

  return {
    full_name: values.full_name.trim(),
    email: values.email.trim(),
    dossier: {
      typed: {
        contact_preference: values.contact_preference,
        children_ages: ages,
        travel_party_notes: values.travel_party_notes,
        estimated_net_worth_usd:
          Number.isFinite(netWorthParsed) && netWorthParsed >= 0
            ? netWorthParsed
            : null,
      },
    },
    dossier_facts,
    profile_facts,
    osint_facts,
    contacts,
    notify: values.notify,
  };
}

export function DossierForm() {
  const [isPending, startTransition] = useTransition();
  const [serverError, setServerError] = useState<string | null>(null);

  const form = useForm<FormInput, unknown, FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const contacts = useFieldArray({ control: form.control, name: "contacts" });
  const facts = useFieldArray({ control: form.control, name: "facts" });

  const onSubmit = (values: FormValues) => {
    setServerError(null);
    startTransition(async () => {
      const result = await createClientAction(toPayload(values));
      // On success the action redirects; we only land here on error.
      if (result && "error" in result) {
        setServerError(result.error);
      }
    });
  };

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className="flex flex-col gap-10"
      >
        <Section
          title="Client basics"
          description="Name and contact channel. The welcome email lands here."
        >
          <div className="grid gap-5 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Full name</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Jane Doe"
                      className={FIELD_DARK}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="jane@example.com"
                      className={FIELD_DARK}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="contact_preference"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Preferred contact</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger className={FIELD_DARK}>
                        <SelectValue placeholder="Select a channel" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {CONTACT_CHANNELS.map((c) => (
                        <SelectItem key={c} value={c}>
                          {c}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          <FormField
            control={form.control}
            name="notify"
            render={({ field }) => (
              <FormItem className="flex flex-row items-start gap-3 rounded-md border border-paper/15 p-4">
                <FormControl>
                  <input
                    type="checkbox"
                    checked={field.value ?? true}
                    onChange={(e) => field.onChange(e.target.checked)}
                    className="mt-0.5 h-4 w-4 shrink-0 accent-brand"
                  />
                </FormControl>
                <div className="space-y-1 leading-none">
                  <FormLabel>Send a welcome email now</FormLabel>
                  <FormDescription className="text-paper/55">
                    On by default. Uncheck to create the client silently and
                    build for them first — you can send the invite later from
                    the roster.
                  </FormDescription>
                </div>
              </FormItem>
            )}
          />
        </Section>

        <Section
          title="Personal notes"
          description="Stable signals about the person — children, household, things the advisor should not forget. Trip-specific party makeup belongs on an itinerary, not here."
        >
          <div className="grid gap-5">
            <FormField
              control={form.control}
              name="children_ages_raw"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Children&rsquo;s ages</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. 7, 10, 14"
                      className={FIELD_DARK}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription className="text-paper/55">
                    Comma or space separated. Ages 0–25.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="travel_party_notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Notes</FormLabel>
                  <FormControl>
                    <Textarea rows={3} className={FIELD_DARK} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="estimated_net_worth_usd"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Estimated net worth (USD)</FormLabel>
                  <FormControl>
                    <Input
                      inputMode="numeric"
                      placeholder="Optional — e.g. 250,000,000"
                      className={FIELD_DARK}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription className="text-paper/55">
                    Private. Never rendered back to the client.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
        </Section>

        <Section
          title="Contacts"
          description="Phone numbers, messenger handles, social. Add as many as you have. The welcome email still goes to the email above."
        >
          <div className="flex flex-col gap-3">
            {contacts.fields.length === 0 ? (
              <p className="font-sans text-sm italic text-paper/55">
                No contacts yet. Add some now or skip — you can add them on
                the client detail page anytime.
              </p>
            ) : null}

            {contacts.fields.map((row, i) => (
              <div
                key={row.id}
                className="grid gap-2 rounded-md border border-paper/15 p-3 sm:grid-cols-[8rem_1fr_8rem_auto]"
              >
                <FormField
                  control={form.control}
                  name={`contacts.${i}.kind` as const}
                  render={({ field }) => (
                    <FormItem>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value ?? "phone_cell"}
                      >
                        <FormControl>
                          <SelectTrigger className={FIELD_DARK}>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {CONTACT_KINDS.map((k) => (
                            <SelectItem key={k} value={k}>
                              {CONTACT_KIND_LABELS[k]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name={`contacts.${i}.value` as const}
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <Input
                          placeholder="Number or handle"
                          className={FIELD_DARK}
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name={`contacts.${i}.label` as const}
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <Input
                          placeholder="Label (optional)"
                          className={FIELD_DARK}
                          {...field}
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
                <div className="flex items-center justify-end">
                  <button
                    type="button"
                    onClick={() => contacts.remove(i)}
                    className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive"
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}

            <div>
              <Button
                type="button"
                variant="outline"
                className="border-paper/20 bg-transparent text-paper hover:bg-paper/10 hover:text-paper"
                onClick={() =>
                  contacts.append({
                    kind: "phone_cell",
                    value: "",
                    label: "",
                  })
                }
              >
                Add contact
              </Button>
            </div>
          </div>
        </Section>

        <Section
          title="Seed facts"
          description="Optional. Drop in anything you already know across the three tiers — it lands on the same fact tables you'll edit on the client detail page later."
        >
          <div className="flex flex-col gap-3">
            {facts.fields.length === 0 ? (
              <p className="font-sans text-sm italic text-paper/55">
                No seeds yet. Add some now or skip — you can record facts on
                the client detail page anytime.
              </p>
            ) : null}

            {facts.fields.map((row, i) => {
              const tier =
                (form.watch(`facts.${i}.tier`) as Tier | undefined) ??
                "dossier";
              const isOsint = tier === "osint";
              const kinds = KIND_OPTIONS[tier];
              return (
                <div
                  key={row.id}
                  className="flex flex-col gap-2 rounded-md border border-paper/15 p-3"
                >
                  <div
                    className={`grid gap-2 ${isOsint ? "sm:grid-cols-[7rem_8rem_1fr_1fr_auto]" : "sm:grid-cols-[7rem_8rem_1fr_auto]"}`}
                  >
                    <FormField
                      control={form.control}
                      name={`facts.${i}.tier` as const}
                      render={({ field }) => (
                        <FormItem>
                          <Select
                            onValueChange={(v) => {
                              const next = v as Tier;
                              field.onChange(next);
                              // Reset kind to a valid default for the new tier.
                              form.setValue(
                                `facts.${i}.kind` as const,
                                DEFAULT_KIND[next],
                              );
                            }}
                            value={field.value ?? "dossier"}
                          >
                            <FormControl>
                              <SelectTrigger className={FIELD_DARK}>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {TIERS.map((t) => (
                                <SelectItem key={t} value={t}>
                                  {TIER_LABELS[t]}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`facts.${i}.kind` as const}
                      render={({ field }) => (
                        <FormItem>
                          <Select
                            onValueChange={field.onChange}
                            value={field.value ?? DEFAULT_KIND[tier]}
                          >
                            <FormControl>
                              <SelectTrigger className={FIELD_DARK}>
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {kinds.map((k) => (
                                <SelectItem key={k} value={k}>
                                  {KIND_LABELS[k] ?? k}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name={`facts.${i}.text` as const}
                      render={({ field }) => (
                        <FormItem>
                          <FormControl>
                            <Input
                              placeholder="Fact text…"
                              className={FIELD_DARK}
                              {...field}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    {isOsint ? (
                      <FormField
                        control={form.control}
                        name={`facts.${i}.url` as const}
                        render={({ field }) => (
                          <FormItem>
                            <FormControl>
                              <Input
                                placeholder="Source URL (optional)"
                                className={FIELD_DARK}
                                {...field}
                              />
                            </FormControl>
                          </FormItem>
                        )}
                      />
                    ) : null}
                    <div className="flex items-center justify-end">
                      <button
                        type="button"
                        onClick={() => facts.remove(i)}
                        className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                  <p className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/45">
                    {TIER_RULES[tier]}
                  </p>
                </div>
              );
            })}

            <div>
              <Button
                type="button"
                variant="outline"
                className="border-paper/20 bg-transparent text-paper hover:bg-paper/10 hover:text-paper"
                onClick={() =>
                  facts.append({
                    tier: "dossier",
                    kind: DEFAULT_KIND["dossier"],
                    text: "",
                    url: "",
                  })
                }
              >
                Add fact
              </Button>
            </div>
          </div>
        </Section>

        {serverError ? (
          <p
            role="alert"
            className="font-sans text-sm font-medium text-destructive"
          >
            {serverError}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-4">
          <Button type="submit" variant="brand" disabled={isPending}>
            {isPending ? "saving…" : "Add client"}
          </Button>
        </div>
      </form>
    </Form>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-5">
      <header className="border-b border-paper/10 pb-3">
        <h2 className="font-serif text-xl tracking-tight text-paper">{title}</h2>
        <p className="mt-1 font-sans text-sm text-paper/65">{description}</p>
      </header>
      {children}
    </section>
  );
}
