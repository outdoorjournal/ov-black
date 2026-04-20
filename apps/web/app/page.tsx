import { InviteEntry } from "./_components/invite-entry";

export default function HomePage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="w-full max-w-md">
        <h1 className="font-serif text-5xl tracking-tight text-ink">
          OV Black
        </h1>
        <p className="mt-3 font-sans text-sm uppercase tracking-[0.3em] text-ink/60">
          By invitation only
        </p>

        <div className="mt-12">
          <InviteEntry />
        </div>
      </div>
    </main>
  );
}
