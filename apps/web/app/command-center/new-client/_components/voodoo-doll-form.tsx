"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState, useTransition } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import type { ClientCreatePayload } from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

// Zod schema mirrors apps/api/app/schemas/clients.py — the typed core is
// strict (enums + bounded ints) and the JSONB long-tail is shallow on
// purpose: the Voodoo Doll shape is intentionally evolvable per S03
// research §Voodoo Doll schema volatility, so we match the backend's
// "dict/list only" posture rather than pinning tighter shapes.

const CONTACT_CHANNELS = ["email", "sms", "whatsapp", "phone"] as const;
const GROUP_TYPES = [
  "solo",
  "couple",
  "family",
  "friends",
  "multigen",
  "corporate",
] as const;
const INTENSITIES = ["low", "medium", "high"] as const;

const passionSchema = z.object({
  label: z.string().trim().min(1, "Add a passion or remove the row."),
  intensity: z.enum(INTENSITIES).default("medium"),
  notes: z.string().trim().max(1000).default(""),
});

const travelHistorySchema = z.object({
  destination: z
    .string()
    .trim()
    .min(1, "Add a destination or remove the row."),
  year: z.string().trim().max(12).default(""),
  notes: z.string().trim().max(1000).default(""),
});

const formSchema = z.object({
  full_name: z.string().trim().min(1, "Required").max(200),
  email: z.string().trim().email("Enter a valid email"),
  contact_preference: z.enum(CONTACT_CHANNELS),
  group_type: z.enum(GROUP_TYPES),
  children_ages_raw: z.string().trim().max(200).default(""),
  travel_party_notes: z.string().trim().max(2000).default(""),
  estimated_net_worth_usd: z.string().trim().max(32).default(""),
  passions: z.array(passionSchema).default([]),
  motivations_fomo: z.string().trim().max(500).default(""),
  motivations_status: z.string().trim().max(500).default(""),
  motivations_bucket_list: z.string().trim().max(500).default(""),
  motivations_notes: z.string().trim().max(2000).default(""),
  travel_history: z.array(travelHistorySchema).default([]),
  triggers_raw: z.string().trim().max(2000).default(""),
  constraints_raw: z.string().trim().max(2000).default(""),
  deal_breakers_raw: z.string().trim().max(2000).default(""),
  dream_trip_signals: z.string().trim().max(2000).default(""),
});

// Input = what the form renders / user edits (defaults may be omitted).
// Output = what the resolver produces (defaults applied → all strings present).
// Passing both to useForm keeps the resolver + handleSubmit callback types
// aligned under exactOptionalPropertyTypes.
type FormInput = z.input<typeof formSchema>;
type FormValues = z.output<typeof formSchema>;

const DEFAULT_VALUES: FormInput = {
  full_name: "",
  email: "",
  contact_preference: "email",
  group_type: "solo",
  children_ages_raw: "",
  travel_party_notes: "",
  estimated_net_worth_usd: "",
  passions: [],
  motivations_fomo: "",
  motivations_status: "",
  motivations_bucket_list: "",
  motivations_notes: "",
  travel_history: [],
  triggers_raw: "",
  constraints_raw: "",
  deal_breakers_raw: "",
  dream_trip_signals: "",
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

function splitTags(raw: string): string[] {
  if (!raw) return [];
  return raw
    .split(/\r?\n|,/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function toPayload(values: FormValues): ClientCreatePayload {
  const ages = parseAges(values.children_ages_raw);
  const netWorth = values.estimated_net_worth_usd.trim();
  const netWorthParsed = netWorth ? Number.parseInt(netWorth, 10) : NaN;

  return {
    full_name: values.full_name.trim(),
    email: values.email.trim(),
    voodoo_doll: {
      typed: {
        contact_preference: values.contact_preference,
        group_type: values.group_type,
        children_ages: ages,
        travel_party_notes: values.travel_party_notes,
        estimated_net_worth_usd:
          Number.isFinite(netWorthParsed) && netWorthParsed >= 0
            ? netWorthParsed
            : null,
      },
      jsonb: {
        passions: values.passions.map((p) => ({
          label: p.label,
          intensity: p.intensity,
          notes: p.notes,
        })),
        motivations: {
          fomo: values.motivations_fomo,
          status: values.motivations_status,
          bucket_list: values.motivations_bucket_list,
          notes: values.motivations_notes,
        },
        travel_history: values.travel_history.map((h) => ({
          destination: h.destination,
          year: h.year,
          notes: h.notes,
        })),
        triggers: splitTags(values.triggers_raw).map((label) => ({ label })),
        constraints: splitTags(values.constraints_raw).map((label) => ({
          label,
        })),
        deal_breakers: splitTags(values.deal_breakers_raw).map((label) => ({
          label,
        })),
        dream_trip_signals: { notes: values.dream_trip_signals },
        osint_notes: {},
      },
    },
  };
}

export function VoodooDollForm() {
  const [isPending, startTransition] = useTransition();
  const [serverError, setServerError] = useState<string | null>(null);

  const form = useForm<FormInput, unknown, FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const passions = useFieldArray({ control: form.control, name: "passions" });
  const travelHistory = useFieldArray({
    control: form.control,
    name: "travel_history",
  });

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
        className="flex flex-col gap-8"
      >
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Client basics</CardTitle>
            <CardDescription>
              Name and contact channel. The invite email lands here.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Full name</FormLabel>
                  <FormControl>
                    <Input placeholder="Jane Doe" {...field} />
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
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                  >
                    <FormControl>
                      <SelectTrigger>
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
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Travel party</CardTitle>
            <CardDescription>
              Who travels with this client and notes the advisor should not
              forget.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5">
            <FormField
              control={form.control}
              name="group_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Group type</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a group type" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {GROUP_TYPES.map((g) => (
                        <SelectItem key={g} value={g}>
                          {g}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="children_ages_raw"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Children&rsquo;s ages</FormLabel>
                  <FormControl>
                    <Input placeholder="e.g. 7, 10, 14" {...field} />
                  </FormControl>
                  <FormDescription>
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
                  <FormLabel>Party notes</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
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
                      placeholder="Optional"
                      {...field}
                    />
                  </FormControl>
                  <FormDescription>
                    Private. Never rendered back to the client.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Passions</CardTitle>
            <CardDescription>
              Things this client cares about deeply. Add a row per passion.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {passions.fields.map((row, i) => (
              <div
                key={row.id}
                className="grid gap-3 rounded-md border border-border p-4 sm:grid-cols-[1fr_9rem_auto]"
              >
                <FormField
                  control={form.control}
                  name={`passions.${i}.label` as const}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Label</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="e.g. Deep-sea diving"
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name={`passions.${i}.intensity` as const}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Intensity</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value ?? "medium"}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {INTENSITIES.map((t) => (
                            <SelectItem key={t} value={t}>
                              {t}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="flex items-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => passions.remove(i)}
                  >
                    Remove
                  </Button>
                </div>
                <div className="sm:col-span-3">
                  <FormField
                    control={form.control}
                    name={`passions.${i}.notes` as const}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Notes</FormLabel>
                        <FormControl>
                          <Textarea rows={2} {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>
            ))}
            <div>
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  passions.append({
                    label: "",
                    intensity: "medium",
                    notes: "",
                  })
                }
              >
                Add passion
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Motivations</CardTitle>
            <CardDescription>
              What drives this client to book. All fields optional.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="motivations_fomo"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>FOMO</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="motivations_status"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Status</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="motivations_bucket_list"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Bucket list</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="motivations_notes"
              render={({ field }) => (
                <FormItem className="sm:col-span-2">
                  <FormLabel>Notes</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Travel history</CardTitle>
            <CardDescription>
              Recent or formative trips. Add a row per trip.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {travelHistory.fields.map((row, i) => (
              <div
                key={row.id}
                className="grid gap-3 rounded-md border border-border p-4 sm:grid-cols-[1fr_9rem_auto]"
              >
                <FormField
                  control={form.control}
                  name={`travel_history.${i}.destination` as const}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Destination</FormLabel>
                      <FormControl>
                        <Input placeholder="e.g. Patagonia" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name={`travel_history.${i}.year` as const}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Year</FormLabel>
                      <FormControl>
                        <Input placeholder="2024" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="flex items-end">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => travelHistory.remove(i)}
                  >
                    Remove
                  </Button>
                </div>
                <div className="sm:col-span-3">
                  <FormField
                    control={form.control}
                    name={`travel_history.${i}.notes` as const}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Notes</FormLabel>
                        <FormControl>
                          <Textarea rows={2} {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>
            ))}
            <div>
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  travelHistory.append({
                    destination: "",
                    year: "",
                    notes: "",
                  })
                }
              >
                Add trip
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">
              Triggers &amp; constraints
            </CardTitle>
            <CardDescription>
              One per line, or comma-separated. Plain language tags.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5 sm:grid-cols-2">
            <FormField
              control={form.control}
              name="triggers_raw"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Triggers</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="constraints_raw"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Constraints</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="deal_breakers_raw"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Deal-breakers</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="dream_trip_signals"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Dream trip</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </CardContent>
        </Card>

        {serverError ? (
          <p
            role="alert"
            className="font-sans text-sm font-medium text-destructive"
          >
            {serverError}
          </p>
        ) : null}

        <div className="flex items-center justify-end gap-4">
          <Button type="submit" disabled={isPending}>
            {isPending ? "saving…" : "Issue invite"}
          </Button>
        </div>
      </form>
    </Form>
  );
}
