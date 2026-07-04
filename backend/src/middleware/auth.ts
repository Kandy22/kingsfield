import { Request, Response, NextFunction } from "express";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const isDev = process.env.NODE_ENV !== "production";
const devLog = (...args: Parameters<typeof console.log>) => {
  if (isDev) console.log(...args);
};

// ── Performance ────────────────────────────────────────────────────────────
// Every authenticated request used to (1) construct a fresh Supabase admin
// client, (2) make a network round-trip to Supabase to validate the JWT
// (admin.auth.getUser), and (3) run a DB query for the MFA preference. The
// frontend fires a burst of parallel requests with the SAME token on each page
// load, so every one of them paid ~170-330ms independently.
//
// Fixes: a single module-level admin client, plus short-TTL in-memory caches
// keyed by token / user. A valid JWT is cached for 60s so only the first
// request in a burst pays the round-trip; the MFA preference is cached the same
// way. TTL is short enough that revocation/preference changes take effect
// within a minute.

let adminSingleton: SupabaseClient | null = null;
function getAdmin(): SupabaseClient | null {
  const supabaseUrl = process.env.SUPABASE_URL ?? "";
  const serviceKey = process.env.SUPABASE_SECRET_KEY ?? "";
  if (!supabaseUrl || !serviceKey) return null;
  if (!adminSingleton) {
    adminSingleton = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false },
    });
  }
  return adminSingleton;
}

const USER_TTL_MS = 60_000;
const MFA_TTL_MS = 60_000;
const userCache = new Map<string, { userId: string; email: string; exp: number }>();
const mfaCache = new Map<string, { on: boolean; exp: number }>();

async function resolveUser(
  admin: SupabaseClient,
  token: string,
): Promise<{ userId: string; email: string } | null> {
  const now = Date.now();
  const hit = userCache.get(token);
  if (hit && hit.exp > now) return { userId: hit.userId, email: hit.email };
  const { data } = await admin.auth.getUser(token);
  if (!data.user) return null;
  const entry = {
    userId: data.user.id,
    email: data.user.email?.toLowerCase() ?? "",
    exp: now + USER_TTL_MS,
  };
  userCache.set(token, entry);
  // Opportunistic cleanup so the map can't grow unbounded.
  if (userCache.size > 500) {
    for (const [k, v] of userCache) if (v.exp <= now) userCache.delete(k);
  }
  return { userId: entry.userId, email: entry.email };
}

function summarizeMfaFactors(
  factors: Array<{
    factor_type?: string;
    status?: string;
  }> | null | undefined,
) {
  return (factors ?? []).map((factor) => ({
    type: factor.factor_type ?? "unknown",
    status: factor.status ?? "unknown",
  }));
}

function isLoginMfaBootstrapRoute(req: Request) {
  const path = req.originalUrl.split("?")[0];
  return (
    (req.method === "GET" || req.method === "POST") &&
    (path === "/user/profile" || path === "/users/profile")
  );
}

async function enforceLoginMfaIfEnabled(
  req: Request,
  res: Response,
  admin: SupabaseClient<any, "public", any>,
  token: string,
) {
  if (isLoginMfaBootstrapRoute(req)) return true;

  const userId = res.locals.userId as string;
  const now = Date.now();
  let mfaOn: boolean;
  const cached = mfaCache.get(userId);
  if (cached && cached.exp > now) {
    mfaOn = cached.on;
  } else {
    const { data, error } = await admin
      .from("user_profiles")
      .select("mfa_on_login")
      .eq("user_id", userId)
      .maybeSingle();
    if (error) {
      devLog("[auth/mfa] login preference lookup failed", {
        method: req.method,
        path: req.originalUrl,
        userId,
        error: error.message,
        code: error.code,
      });
      if (error.code === "42703") return true;
      res.status(500).json({ detail: error.message });
      return false;
    }
    mfaOn = (data as { mfa_on_login?: boolean } | null)?.mfa_on_login === true;
    mfaCache.set(userId, { on: mfaOn, exp: now + MFA_TTL_MS });
  }
  if (!mfaOn) return true;

  const { data: assurance, error: assuranceError } =
    await admin.auth.mfa.getAuthenticatorAssuranceLevel(token);

  if (assuranceError) {
    devLog("[auth/mfa] login assurance lookup failed", {
      method: req.method,
      path: req.originalUrl,
      userId: res.locals.userId,
      error: assuranceError.message,
    });
    res.status(401).json({ detail: assuranceError.message });
    return false;
  }

  if (assurance.nextLevel === "aal2" && assurance.currentLevel !== "aal2") {
    devLog("[auth/mfa] login verification required", {
      method: req.method,
      path: req.originalUrl,
      userId: res.locals.userId,
    });
    res.status(403).json({
      code: "mfa_verification_required",
      detail: "MFA verification required",
    });
    return false;
  }

  return true;
}

export async function requireAuth(
  req: Request,
  res: Response,
  next: NextFunction,
): Promise<void> {
  const auth = req.headers.authorization ?? "";
  if (!auth.startsWith("Bearer ")) {
    res.status(401).json({ detail: "Missing or invalid Authorization header" });
    return;
  }
  const token = auth.slice(7).trim();

  const admin = getAdmin();
  if (!admin) {
    res.status(500).json({ detail: "Server auth is not configured" });
    return;
  }

  const resolved = await resolveUser(admin, token);
  if (!resolved) {
    res.status(401).json({ detail: "Invalid or expired token" });
    return;
  }

  res.locals.userId = resolved.userId;
  res.locals.userEmail = resolved.email;
  res.locals.token = token;
  if (!(await enforceLoginMfaIfEnabled(req, res, admin, token))) {
    return;
  }
  next();
}

export async function requireMfaIfEnrolled(
  req: Request,
  res: Response,
  next: NextFunction,
): Promise<void> {
  const token = typeof res.locals.token === "string" ? res.locals.token : "";
  if (!token) {
    devLog("[auth/mfa] missing auth session", {
      method: req.method,
      path: req.originalUrl,
    });
    res.status(401).json({ detail: "Missing auth session" });
    return;
  }

  const admin = getAdmin();
  if (!admin) {
    res.status(500).json({ detail: "Server auth is not configured" });
    return;
  }
  const { data, error } =
    await admin.auth.mfa.getAuthenticatorAssuranceLevel(token);

  if (error) {
    devLog("[auth/mfa] assurance lookup failed", {
      method: req.method,
      path: req.originalUrl,
      userId: res.locals.userId,
      error: error.message,
    });
    res.status(401).json({ detail: error.message });
    return;
  }

  devLog("[auth/mfa] assurance level", {
    method: req.method,
    path: req.originalUrl,
    userId: res.locals.userId,
    currentLevel: data.currentLevel,
    nextLevel: data.nextLevel,
    required: data.nextLevel === "aal2" && data.currentLevel !== "aal2",
  });

  if (isDev) {
    const { data: userData, error: userError } = await admin.auth.getUser(token);
    devLog("[auth/mfa] user factors", {
      method: req.method,
      path: req.originalUrl,
      userId: res.locals.userId,
      factorCount: userData.user?.factors?.length ?? 0,
      factors: summarizeMfaFactors(userData.user?.factors),
      error: userError?.message ?? null,
    });
  }

  if (data.nextLevel === "aal2" && data.currentLevel !== "aal2") {
    devLog("[auth/mfa] verification required", {
      method: req.method,
      path: req.originalUrl,
      userId: res.locals.userId,
    });
    res.status(403).json({
      code: "mfa_verification_required",
      detail: "MFA verification required",
    });
    return;
  }

  next();
}
