const users = new Map();
const sessions = new Map();

export async function findUserByEmail(email) {
  return users.get(email.trim().toLowerCase()) ?? null;
}

export async function saveSession(session) {
  sessions.set(session.token, session);
  return session;
}

export const sessionStore = {
  async list() {
    return [...sessions.values()];
  },
  remove(token) {
    return sessions.delete(token);
  },
};
