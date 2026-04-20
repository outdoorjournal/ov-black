// Small runtime guard so we fail loud when deploy-time env wiring is missing,
// rather than shipping an app that silently creates a misconfigured Supabase
// client and throws on first request.

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `Missing required environment variable: ${name}. ` +
        `Set it in .env.local (development) or in the hosting env (Vercel/ECS).`,
    );
  }
  return value;
}

export function publicEnv(): {
  supabaseUrl: string;
  supabaseAnonKey: string;
  apiBaseUrl: string;
} {
  return {
    supabaseUrl: required("NEXT_PUBLIC_SUPABASE_URL"),
    supabaseAnonKey: required("NEXT_PUBLIC_SUPABASE_ANON_KEY"),
    apiBaseUrl: required("NEXT_PUBLIC_API_BASE_URL"),
  };
}
