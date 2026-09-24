import { state } from "./state.js";
export async function api(path, body, method) {
  const response = await fetch("/api/v1" + path, {
    method: method || (body ? "POST" : "GET"),
    headers: {
      ...(state.token ? { Authorization: "Bearer " + state.token } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error?.message || "请求失败");
  return data;
}
