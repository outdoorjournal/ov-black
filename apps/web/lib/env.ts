// Runtime public config — read at REQUEST time, never baked at `next build`.
//
// These four values (Supabase URL + anon key, the API base URL, the Mapbox
// public token) are non-secret and browser-exposed. We deliberately do NOT use
// `NEXT_PUBLIC_*` for them in code paths that matter: those get string-inlined
// into the bundle at build time, which would force a per-environment image and a
// rebuild to change a URL. Instead:
//   - On the server we read them from `process.env` at request time, under
//     non-`NEXT_PUBLIC_` names (OVB_*) so Next never inlines them. The ECS task
//     definition injects them (see infra/cdk/lib/api-stack.ts).
//   - On the client we read them from `window.__OVB_ENV__`, which the root
//     layout serializes from the same server-side values (see app/layout.tsx).
// One built image is therefore configured entirely by runtime env.
//
// `NEXT_PUBLIC_*` is still honored as a fallback so existing local `.env.local`
// files keep working with `next dev`.

export interface PublicEnv {
  supabaseUrl?: string | undefined;
  supabaseAnonKey?: string | undefined;
  apiBaseUrl?: string | undefined;
  mapboxToken?: string | undefined;
}

declare global {
  interface Window {
    __OVB_ENV__?: PublicEnv;
  }
}

/**
 * Resolve the raw public env from whichever source is authoritative in the
 * current execution context. Server + jsdom read `process.env`; the browser
 * reads the layout-injected `window.__OVB_ENV__`.
 */
export function resolvePublicEnv(): PublicEnv {
  if (typeof window !== "undefined" && window.__OVB_ENV__) {
    return window.__OVB_ENV__;
  }
  if (typeof process !== "undefined" && process.env) {
    // Bracket access: OVB_* aren't declared on ProcessEnv (index signature), and
    // bracket also keeps Next from inlining these — they must stay runtime reads.
    return {
      supabaseUrl:
        process.env["OVB_SUPABASE_URL"] ??
        process.env["NEXT_PUBLIC_SUPABASE_URL"],
      supabaseAnonKey:
        process.env["OVB_SUPABASE_ANON_KEY"] ??
        process.env["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
      apiBaseUrl:
        process.env["OVB_API_BASE_URL"] ??
        process.env["NEXT_PUBLIC_API_BASE_URL"],
      mapboxToken:
        process.env["OVB_MAPBOX_TOKEN"] ??
        process.env["NEXT_PUBLIC_MAPBOX_API_KEY"],
    };
  }
  return {};
}

function required(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(
      `Missing required runtime config: ${name}. ` +
        `Set OVB_* in the hosting env (ECS task definition) or NEXT_PUBLIC_* in ` +
        `.env.local for local dev.`,
    );
  }
  return value;
}

export function publicEnv(): {
  supabaseUrl: string;
  supabaseAnonKey: string;
  apiBaseUrl: string;
} {
  const env = resolvePublicEnv();
  return {
    supabaseUrl: required(env.supabaseUrl, "supabaseUrl"),
    supabaseAnonKey: required(env.supabaseAnonKey, "supabaseAnonKey"),
    apiBaseUrl: required(env.apiBaseUrl, "apiBaseUrl"),
  };
}

/** Optional — callers degrade gracefully (e.g. hide the map) when unset. */
export function mapboxToken(): string | undefined {
  const token = resolvePublicEnv().mapboxToken;
  return token && token.length > 0 ? token : undefined;
}

/**
 * Demo/dev flag — when truthy, the pay page offers a "pay with test card" button
 * that submits the Braintree sandbox nonce so a demo flows without typing a card.
 * Read server-side and passed as a prop; NEVER enable in prod (the gateway must be
 * the Fake/sandbox gateway for the nonce to succeed). Bracket read so Next never
 * inlines it. Truthy values: "1" / "true" / "yes" (case-insensitive).
 */
export function demoTestCardEnabled(): boolean {
  const raw =
    (typeof process !== "undefined" && process.env
      ? process.env["OVB_DEMO_TEST_CARD"] ?? process.env["NEXT_PUBLIC_DEMO_TEST_CARD"]
      : undefined) ?? "";
  return ["1", "true", "yes"].includes(raw.trim().toLowerCase());
}
