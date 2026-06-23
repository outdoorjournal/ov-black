// Liveness probe for the shared ALB's web target group. Kept deliberately
// dumb: it touches no env, no Supabase, no API — so a misconfigured
// NEXT_PUBLIC_* value (which would throw inside publicEnv() on the real pages)
// can't flap the target group unhealthy. A 200 here just proves the Next
// standalone server is up and serving. Mirrors apps/api's GET /health.
export const dynamic = "force-dynamic";

export function GET() {
  return new Response("ok", {
    status: 200,
    headers: { "content-type": "text/plain" },
  });
}
