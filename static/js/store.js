export const store = {
  status: null,
  wizard: null,
  guildCache: null,
  guildCacheId: null,
};

export function setStatus(status) {
  store.status = status;
  store.wizard = status?.wizard || null;
  if (store.guildCacheId && store.guildCacheId !== status?.guild?.id) {
    store.guildCache = null;
    store.guildCacheId = null;
  }
}
