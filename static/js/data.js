import { api } from "./api.js";
import { store } from "./store.js";

export async function guildData(force = false) {
  const guildId = store.status?.guild?.id;
  if (!guildId) return null;
  if (!force && store.guildCache && store.guildCacheId === guildId) {
    return store.guildCache;
  }
  const data = await api(`/api/discord/guild/${guildId}`);
  store.guildCache = data;
  store.guildCacheId = guildId;
  return data;
}

export function clearGuildData() {
  store.guildCache = null;
  store.guildCacheId = null;
}
