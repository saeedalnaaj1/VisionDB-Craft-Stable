// Pure interaction helpers shared by the Annotate panel and its regression
// tests. They intentionally have no browser or backend dependencies.

export function shouldIgnoreAnnotationShortcut(target, key) {
  const tag = String(target?.tagName || "").toUpperCase();
  if (target?.isContentEditable || tag === "TEXTAREA") return true;
  if (tag === "SELECT") return key !== "w";
  if (tag !== "INPUT") return false;
  const type = String(target?.type || "text").toLowerCase();
  return !["button", "checkbox", "radio", "range", "submit"].includes(type);
}

export function remapHiddenAnnotationIndices(indices, deletedIndex) {
  return [...indices]
    .filter(index => index !== deletedIndex)
    .map(index => index > deletedIndex ? index - 1 : index);
}
