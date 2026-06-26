"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState, useTransition } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";

import type { PartyMemberCreate, PartyMemberDetail } from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

// The travel-party member form, shared by the traveler self-service manager
// and the advisor's client-detail panel. Surface-agnostic: the caller passes
// an `onSubmit` that forwards the mapped payload to the right action (create or
// update). Built on react-hook-form + zodResolver per the V2 contract; styled
// for the dark (paper-on-ink) surfaces, like the fact / contact editors.

const loyaltySchema = z.object({
  program: z.string().trim().max(120).default(""),
  number: z.string().trim().max(120).default(""),
});

const formSchema = z.object({
  full_name: z.string().trim().min(1, "Required").max(200),
  date_of_birth: z.string().trim().max(10).default(""),
  nationality: z.string().trim().max(120).default(""),
  dietary: z.string().trim().max(2000).default(""),
  medical: z.string().trim().max(2000).default(""),
  mobility: z.string().trim().max(2000).default(""),
  relationship_to_primary: z.string().trim().max(120).default(""),
  is_primary: z.boolean().default(false),
  notes: z.string().trim().max(4000).default(""),
  loyalty_programs: z.array(loyaltySchema).default([]),
  ec_name: z.string().trim().max(200).default(""),
  ec_relationship: z.string().trim().max(120).default(""),
  ec_phone: z.string().trim().max(60).default(""),
});

type FormInput = z.input<typeof formSchema>;
type FormValues = z.output<typeof formSchema>;

function orNull(s: string): string | null {
  const t = s.trim();
  return t ? t : null;
}

export function toPayload(values: FormValues): PartyMemberCreate {
  const loyalty = values.loyalty_programs
    .map((l) => ({ program: l.program.trim(), number: l.number.trim() }))
    .filter((l) => l.program && l.number);

  const ecName = values.ec_name.trim();
  const ecRel = values.ec_relationship.trim();
  const ecPhone = values.ec_phone.trim();
  const hasEmergency = Boolean(ecName || ecRel || ecPhone);

  return {
    full_name: values.full_name.trim(),
    date_of_birth: orNull(values.date_of_birth),
    nationality: orNull(values.nationality),
    dietary: orNull(values.dietary),
    medical: orNull(values.medical),
    mobility: orNull(values.mobility),
    relationship_to_primary: orNull(values.relationship_to_primary),
    is_primary: values.is_primary,
    notes: orNull(values.notes),
    loyalty_programs: loyalty,
    emergency_contact: hasEmergency
      ? {
          name: ecName || null,
          relationship: ecRel || null,
          phone: ecPhone || null,
        }
      : null,
  };
}

function fromMember(member: PartyMemberDetail): FormInput {
  const ec = member.emergency_contact ?? {};
  return {
    full_name: member.full_name,
    date_of_birth: member.date_of_birth ?? "",
    nationality: member.nationality ?? "",
    dietary: member.dietary ?? "",
    medical: member.medical ?? "",
    mobility: member.mobility ?? "",
    relationship_to_primary: member.relationship_to_primary ?? "",
    is_primary: member.is_primary,
    notes: member.notes ?? "",
    loyalty_programs: member.loyalty_programs.map(
      (l: Record<string, unknown>) => ({
        program: typeof l["program"] === "string" ? l["program"] : "",
        number: typeof l["number"] === "string" ? l["number"] : "",
      }),
    ),
    ec_name: typeof ec["name"] === "string" ? ec["name"] : "",
    ec_relationship:
      typeof ec["relationship"] === "string" ? ec["relationship"] : "",
    ec_phone: typeof ec["phone"] === "string" ? ec["phone"] : "",
  };
}

const EMPTY: FormInput = {
  full_name: "",
  date_of_birth: "",
  nationality: "",
  dietary: "",
  medical: "",
  mobility: "",
  relationship_to_primary: "",
  is_primary: false,
  notes: "",
  loyalty_programs: [],
  ec_name: "",
  ec_relationship: "",
  ec_phone: "",
};

const inputCls =
  "h-9 w-full rounded-sm border border-paper/20 bg-transparent px-2 font-sans text-sm text-paper placeholder:text-paper/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-paper/30";
const labelCls =
  "font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55";

export function PartyMemberForm({
  member,
  onSubmit,
  onCancel,
  submitLabel = "Save traveler",
}: {
  member?: PartyMemberDetail;
  onSubmit: (
    payload: PartyMemberCreate,
  ) => Promise<{ ok: true } | { error: string }>;
  onCancel?: () => void;
  submitLabel?: string;
}) {
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const form = useForm<FormInput, unknown, FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: member ? fromMember(member) : EMPTY,
  });
  const { register, control, handleSubmit, formState } = form;
  const loyalty = useFieldArray({ control, name: "loyalty_programs" });

  const submit = (values: FormValues) => {
    setServerError(null);
    startTransition(async () => {
      const result = await onSubmit(toPayload(values));
      if ("error" in result) {
        setServerError(result.error);
      } else if (!member) {
        form.reset(EMPTY);
        loyalty.replace([]);
      }
    });
  };

  return (
    <form
      onSubmit={handleSubmit(submit)}
      className="flex flex-col gap-5 rounded-sm border border-paper/15 bg-paper/[0.06] p-4"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Full name</span>
          <input
            {...register("full_name")}
            placeholder="As it appears on their passport"
            className={inputCls}
            autoFocus
          />
          {formState.errors.full_name ? (
            <span role="alert" className="font-sans text-xs text-destructive">
              {formState.errors.full_name.message}
            </span>
          ) : null}
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Date of birth</span>
          <input
            type="date"
            {...register("date_of_birth")}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Nationality</span>
          <input
            {...register("nationality")}
            placeholder="e.g. United States"
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Relationship</span>
          <input
            {...register("relationship_to_primary")}
            placeholder="e.g. Spouse, Child"
            className={inputCls}
          />
        </label>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Dietary</span>
          <Textarea
            rows={2}
            {...register("dietary")}
            placeholder="Allergies, restrictions, preferences"
            className="border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Medical</span>
          <Textarea
            rows={2}
            {...register("medical")}
            placeholder="Conditions, medications"
            className="border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Mobility</span>
          <Textarea
            rows={2}
            {...register("mobility")}
            placeholder="Access needs"
            className="border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
          />
        </label>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className={labelCls}>Loyalty programs</legend>
        {loyalty.fields.map((row, i) => (
          <div key={row.id} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <input
              {...register(`loyalty_programs.${i}.program`)}
              placeholder="Programme (e.g. AAdvantage)"
              className={inputCls}
            />
            <input
              {...register(`loyalty_programs.${i}.number`)}
              placeholder="Membership number"
              className={inputCls}
            />
            <button
              type="button"
              onClick={() => loyalty.remove(i)}
              className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive"
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => loyalty.append({ program: "", number: "" })}
          className="self-start font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-paper"
        >
          + Add programme
        </button>
      </fieldset>

      <fieldset className="grid gap-2 sm:grid-cols-3">
        <legend className={`${labelCls} sm:col-span-3`}>
          Emergency contact
        </legend>
        <input
          {...register("ec_name")}
          placeholder="Name"
          className={inputCls}
        />
        <input
          {...register("ec_relationship")}
          placeholder="Relationship"
          className={inputCls}
        />
        <input
          {...register("ec_phone")}
          placeholder="Phone"
          className={inputCls}
        />
      </fieldset>

      <label className="flex flex-col gap-1">
        <span className={labelCls}>Notes</span>
        <Textarea
          rows={2}
          {...register("notes")}
          placeholder="Anything else the concierge should know"
          className="border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
        />
      </label>

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          {...register("is_primary")}
          className="h-4 w-4 accent-paper"
        />
        <span className="font-sans text-sm text-paper/80">
          Primary traveler for this household
        </span>
      </label>

      {serverError ? (
        <p role="alert" className="font-sans text-xs font-medium text-destructive">
          {serverError}
        </p>
      ) : null}

      <div className="flex items-center justify-end gap-3">
        {onCancel ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={isPending}
            className="text-paper/70 hover:bg-paper/10 hover:text-paper"
          >
            Cancel
          </Button>
        ) : null}
        <Button
          type="submit"
          size="sm"
          disabled={isPending}
          className="bg-paper text-ink hover:bg-paper/90"
        >
          {isPending ? "saving…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
