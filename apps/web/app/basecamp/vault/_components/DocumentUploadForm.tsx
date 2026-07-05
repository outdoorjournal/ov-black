"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRef, useState, useTransition } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import type {
  DocumentInitRequest,
  DocumentType,
  PartyMemberDetail,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

// The document upload form, shared by the traveler vault and the advisor's
// client-detail panel. It owns the two-step presigned flow: the caller passes an
// `onInit` (→ presigned PUT + document id) and an `onComplete`; this component
// PUTs the file straight to S3 in between. Built on react-hook-form + zodResolver
// per the V3 contract; styled for the dark surfaces like the party form.

const DOC_TYPES: { value: DocumentType; label: string }[] = [
  { value: "passport", label: "Passport" },
  { value: "visa", label: "Visa" },
  { value: "drivers_license", label: "Driver's licence" },
  { value: "national_id", label: "National ID" },
  { value: "vaccination", label: "Vaccination" },
  { value: "insurance", label: "Insurance" },
  { value: "loyalty_card", label: "Loyalty card" },
  { value: "other", label: "Other" },
];

const formSchema = z.object({
  doc_type: z.enum([
    "passport",
    "visa",
    "drivers_license",
    "national_id",
    "vaccination",
    "insurance",
    "loyalty_card",
    "other",
  ]),
  label: z.string().trim().max(200).default(""),
  party_member_id: z.string().trim().default(""),
  expires_at: z.string().trim().max(10).default(""),
  notes: z.string().trim().max(4000).default(""),
});

type FormInput = z.input<typeof formSchema>;
type FormValues = z.output<typeof formSchema>;

const EMPTY: FormInput = {
  doc_type: "passport",
  label: "",
  party_member_id: "",
  expires_at: "",
  notes: "",
};

const inputCls =
  "h-9 w-full rounded-sm border border-paper/20 bg-transparent px-2 font-sans text-sm text-paper placeholder:text-paper/40 focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-paper/30";
const labelCls =
  "font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55";

export function DocumentUploadForm({
  members,
  onInit,
  onComplete,
  onDone,
  onCancel,
}: {
  members: PartyMemberDetail[];
  onInit: (
    meta: DocumentInitRequest,
  ) => Promise<
    { ok: true; uploadUrl: string; documentId: string } | { error: string }
  >;
  onComplete: (
    documentId: string,
    sizeBytes: number | null,
  ) => Promise<{ ok: true } | { error: string }>;
  onDone?: () => void;
  onCancel?: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { register, handleSubmit } = useForm<FormInput, unknown, FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: EMPTY,
  });

  const orNull = (s: string): string | null => (s.trim() ? s.trim() : null);

  const submit = (values: FormValues) => {
    setServerError(null);
    setFileError(null);
    if (!file) {
      setFileError("Choose a file to upload.");
      return;
    }
    const meta: DocumentInitRequest = {
      doc_type: values.doc_type,
      file_name: file.name,
      content_type: file.type || "application/octet-stream",
      label: orNull(values.label),
      party_member_id: values.party_member_id ? values.party_member_id : null,
      expires_at: orNull(values.expires_at),
      notes: orNull(values.notes),
    };
    startTransition(async () => {
      const init = await onInit(meta);
      if ("error" in init) {
        setServerError(init.error);
        return;
      }
      // The browser uploads the bytes straight to S3 via the presigned PUT.
      try {
        const res = await fetch(init.uploadUrl, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": meta.content_type },
        });
        if (!res.ok) {
          setServerError("Upload failed. Please try again.");
          return;
        }
      } catch {
        setServerError("Upload failed. Please try again.");
        return;
      }
      const done = await onComplete(init.documentId, file.size);
      if ("error" in done) {
        setServerError(done.error);
        return;
      }
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      onDone?.();
    });
  };

  return (
    <form
      onSubmit={handleSubmit(submit)}
      className="flex flex-col gap-5 rounded-sm border border-paper/15 bg-paper/6 p-4"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Type</span>
          <select {...register("doc_type")} className={inputCls}>
            {DOC_TYPES.map((t) => (
              <option key={t.value} value={t.value} className="text-ink">
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Label</span>
          <input
            {...register("label")}
            placeholder="e.g. Mum's passport"
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Belongs to</span>
          <select {...register("party_member_id")} className={inputCls}>
            <option value="" className="text-ink">
              — whole household —
            </option>
            {members.map((m) => (
              <option key={m.id} value={m.id} className="text-ink">
                {m.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>Expires</span>
          <input type="date" {...register("expires_at")} className={inputCls} />
        </label>
      </div>

      <label className="flex flex-col gap-1">
        <span className={labelCls}>File</span>
        <input
          ref={fileInputRef}
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full font-sans text-sm text-paper/80 file:mr-3 file:rounded-sm file:border file:border-paper/20 file:bg-transparent file:px-3 file:py-1.5 file:font-sans file:text-xs file:uppercase file:tracking-[0.16em] file:text-paper hover:file:bg-paper/10"
        />
        {fileError ? (
          <span role="alert" className="font-sans text-xs text-destructive">
            {fileError}
          </span>
        ) : null}
      </label>

      <label className="flex flex-col gap-1">
        <span className={labelCls}>Notes</span>
        <Textarea
          rows={2}
          {...register("notes")}
          placeholder="Anything the concierge should know"
          className="border-paper/20 bg-transparent text-paper placeholder:text-paper/40 focus-visible:ring-paper/30"
        />
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
          {isPending ? "uploading…" : "Upload document"}
        </Button>
      </div>
    </form>
  );
}
