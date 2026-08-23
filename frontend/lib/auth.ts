import "server-only";

import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

const COOKIE_NAME = process.env.NODE_ENV === "production" ? "__Host-admin_session" : "admin_session";
const SESSION_TTL_SECONDS = 8 * 60 * 60;

function secret() {
  return process.env.ADMIN_SESSION_SECRET || process.env.ADMIN_DASHBOARD_TOKEN || "";
}

function signature(timestamp: string) {
  return createHmac("sha256", secret()).update(timestamp).digest("base64url");
}

export function isDashboardConfigured() {
  return Boolean(process.env.ADMIN_DASHBOARD_TOKEN);
}

export function validAdminToken(candidate: string) {
  const expected = process.env.ADMIN_DASHBOARD_TOKEN || "";
  if (!expected || candidate.length > 256 || candidate.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(candidate), Buffer.from(expected));
}

export function createSessionValue() {
  const timestamp = String(Math.floor(Date.now() / 1000));
  return `${timestamp}.${signature(timestamp)}`;
}

export function sessionCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  };
}

export async function hasValidSession() {
  if (!isDashboardConfigured() || !secret()) return false;
  const value = (await cookies()).get(COOKIE_NAME)?.value;
  if (!value) return false;
  const [timestamp, provided] = value.split(".");
  const age = Number(timestamp);
  const ageSeconds = Date.now() / 1000 - age;
  if (!timestamp || !provided || !Number.isFinite(age) || ageSeconds < 0 || ageSeconds > SESSION_TTL_SECONDS) return false;
  const expected = signature(timestamp);
  if (provided.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(provided), Buffer.from(expected));
}

export { COOKIE_NAME };
