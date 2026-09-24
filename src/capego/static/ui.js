import { labels } from "./state.js";
export const $ = (id) => document.getElementById(id);
export function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
export function notice(text, error = false) {
  $("notice").hidden = false;
  $("notice").textContent = text;
  $("notice").className = error ? "error" : "";
}
export async function action(fn) {
  try {
    await fn();
  } catch (e) {
    notice(e.message, true);
  }
}
export function tag(value) {
  return el(
    "span",
    labels[value] || value,
    "tag " +
      (["complete", "succeeded", "usable"].includes(value)
        ? "good"
        : ["failed", "integrity_failed", "excluded"].includes(value)
          ? "warn"
          : ""),
  );
}
export function view(name) {
  for (const v of document.querySelectorAll(".view"))
    v.hidden = v.id !== "view-" + name;
  for (const b of document.querySelectorAll(".nav"))
    b.classList.toggle("active", b.dataset.view === name);
}
