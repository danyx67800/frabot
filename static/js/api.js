export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { "X-Requested-With": "FraBot", ...(options.headers || {}) };
  let body = options.body;
  if (body && typeof body !== "string" && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, { ...options, method, headers, body });
  } catch (error) {
    throw new ApiError("Impossibile raggiungere il pannello.", 0);
  }
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json().catch(() => ({})) : {};
  if (!response.ok) {
    throw new ApiError(data.detail || `Errore ${response.status}`, response.status);
  }
  return data;
}

export function downloadUrl(path, filename) {
  const link = document.createElement("a");
  link.href = path;
  if (filename) link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export async function downloadJson(path) {
  const response = await fetch(path, { headers: { "X-Requested-With": "FraBot" } });
  if (!response.ok) throw new ApiError("Download non riuscito.", response.status);
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : "frabot.json";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function errorMessage(error) {
  return error instanceof ApiError ? error.message : "Errore imprevisto.";
}
