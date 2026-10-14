import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

/**
 * The browser's Supabase client, used only for signing in and holding the
 * session. All deal data comes from the H9N API, which checks the session's
 * access token itself (Milestone 2.5).
 *
 * Created on first use rather than at import, so pages still build when the
 * env values are absent (e.g. in CI).
 */
export function getSupabase(): SupabaseClient {
  if (client) return client;

  const problem = supabaseConfigError();
  if (problem) throw new Error(problem);
  client = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!);
  return client;
}

/** A message explaining what's missing, or null when Supabase is configured. */
export function supabaseConfigError(): string | null {
  if (process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) return null;
  return "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in frontend/.env.local.";
}
