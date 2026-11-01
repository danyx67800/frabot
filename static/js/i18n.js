let dictionary = {};

export async function loadI18n(lang = "it") {
  const response = await fetch(`/static/i18n/${lang}.json`, { cache: "no-cache" });
  if (!response.ok) throw new Error("i18n");
  dictionary = await response.json();
}

export function t(key, vars = {}) {
  const parts = String(key).split(".");
  let value = dictionary;
  for (const part of parts) {
    if (value == null) break;
    value = value[part];
  }
  if (value == null) return key;
  if (Array.isArray(value)) return value;
  let text = String(value);
  for (const [name, replacement] of Object.entries(vars)) {
    text = text.split(`{${name}}`).join(String(replacement));
  }
  return text;
}

export function tList(key) {
  const value = t(key);
  return Array.isArray(value) ? value : [];
}

export function raw() {
  return dictionary;
}
