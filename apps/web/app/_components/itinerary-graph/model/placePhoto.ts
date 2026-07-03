import { resolvePublicEnv } from "@/lib/env";

// Build the loadable image URL for a Places photo from its signed proxy token.
//
// The backend never hands the browser a raw Google photo reference or API key —
// card metadata carries only an HS256-signed `photo_token`. The image itself is
// served by the keyed backend proxy, which resolves the token to a keyless CDN
// URL server-side. We point an <img> at that proxy here, building the absolute
// URL from the runtime-configured API base (a relative path would wrongly
// resolve against the web origin, where the /japan/* fixtures live).
//
// Returns undefined when there's no token or no configured API base, so callers
// fall through to the snapshot cover / gradient stub.
export function placePhotoUrl(token: string | undefined): string | undefined {
  if (!token) return undefined;
  const base = resolvePublicEnv().apiBaseUrl;
  if (!base) return undefined;
  return `${base.replace(/\/+$/, "")}/integrations/google-places/photo?token=${encodeURIComponent(token)}`;
}
