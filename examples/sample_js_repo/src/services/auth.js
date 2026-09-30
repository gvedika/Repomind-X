import crypto from "node:crypto";
import { findUserByEmail, saveSession } from "./userStore.js";
import { logger } from "../utils/logger.js";

const TOKEN_TTL_MS = 60 * 60 * 1000;

/**
 * Derive a salted PBKDF2 digest so stored credentials never contain the raw secret.
 */
export function hashPassword(password, salt) {
  return crypto.pbkdf2Sync(password, salt, 100000, 64, "sha512").toString("hex");
}

/**
 * Compare two digests in constant time to avoid leaking information through timing.
 */
function safeEqual(a, b) {
  const left = Buffer.from(a, "hex");
  const right = Buffer.from(b, "hex");
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

export async function login(email, password) {
  const user = await findUserByEmail(email);
  if (!user) {
    logger.warn("unknown account", { email });
    return null;
  }
  const digest = hashPassword(password, user.salt);
  if (!safeEqual(digest, user.passwordHash)) {
    logger.warn("bad credentials", { email });
    return null;
  }
  const token = crypto.randomBytes(32).toString("hex");
  await saveSession({ token, userId: user.id, expiresAt: Date.now() + TOKEN_TTL_MS });
  return token;
}

export class SessionManager {
  constructor(store) {
    this.store = store;
  }

  /** Drop sessions whose expiry timestamp is in the past. */
  async purgeExpired(now = Date.now()) {
    const sessions = await this.store.list();
    const expired = sessions.filter((s) => s.expiresAt < now);
    await Promise.all(expired.map((s) => this.store.remove(s.token)));
    return expired.length;
  }

  isValid = (session) => Boolean(session) && session.expiresAt > Date.now();
}
