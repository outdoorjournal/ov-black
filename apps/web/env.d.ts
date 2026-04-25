declare namespace NodeJS {
  interface ProcessEnv {
    NEXT_PUBLIC_SUPABASE_URL?: string;
    NEXT_PUBLIC_SUPABASE_ANON_KEY?: string;
    NEXT_PUBLIC_API_BASE_URL?: string;
    NEXT_PUBLIC_MAPBOX_API_KEY?: string;
    NEXT_PUBLIC_SERVER_MAPBOX_API_KEY?: string;
  }
}
