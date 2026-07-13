// One-off: create (or reset) a dedicated DEMO account for no-login demo mode.
// Uses the service key from backend/.env. Safe to re-run — idempotent.
import { createClient } from "@supabase/supabase-js";
import dotenv from "dotenv";
dotenv.config();

const url = process.env.SUPABASE_URL;
const serviceKey =
  process.env.SUPABASE_SERVICE_ROLE_KEY ||
  process.env.SUPABASE_SECRET_KEY ||
  process.env.SUPABASE_SERVICE_KEY;

if (!url || !serviceKey) {
  console.error("Missing SUPABASE_URL or service key in backend/.env");
  process.exit(1);
}

const DEMO_EMAIL = process.env.DEMO_EMAIL || "demo@kingsfield.app";
// No hardcoded password — pass DEMO_PASSWORD in the env when running this script.
const DEMO_PASSWORD = process.env.DEMO_PASSWORD;
if (!DEMO_PASSWORD) {
  console.error("Set DEMO_PASSWORD in the env, e.g. DEMO_PASSWORD=... node backend/scripts/create-demo-user.mjs");
  process.exit(1);
}

const admin = createClient(url, serviceKey, {
  auth: { autoRefreshToken: false, persistSession: false },
});

// Is the demo user already there?
const { data: list } = await admin.auth.admin.listUsers({ perPage: 1000 });
const existing = list?.users?.find((u) => u.email === DEMO_EMAIL);

let userId;
if (existing) {
  // Reset password + ensure confirmed
  const { data, error } = await admin.auth.admin.updateUserById(existing.id, {
    password: DEMO_PASSWORD,
    email_confirm: true,
  });
  if (error) throw error;
  userId = data.user.id;
  console.log(`Demo user existed — password reset. id=${userId}`);
} else {
  const { data, error } = await admin.auth.admin.createUser({
    email: DEMO_EMAIL,
    password: DEMO_PASSWORD,
    email_confirm: true,
  });
  if (error) throw error;
  userId = data.user.id;
  console.log(`Demo user created. id=${userId}`);
}

// Make sure the demo account never trips MFA-on-login.
const { error: profErr } = await admin
  .from("user_profiles")
  .update({ mfa_on_login: false, display_name: "Demo User" })
  .eq("user_id", userId);
if (profErr) console.warn("Could not update user_profiles (may not exist yet):", profErr.message);

console.log(`\nDEMO_EMAIL=${DEMO_EMAIL}`);
console.log(`DEMO_PASSWORD=${DEMO_PASSWORD}`);
console.log("Done.");
