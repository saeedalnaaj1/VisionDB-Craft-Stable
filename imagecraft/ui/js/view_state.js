// Pure view-state decision used by Viewer.setImage(). Keeping this separate
// makes the annotation zoom contract testable without a browser or canvas.

export function preservedImageView(preserveView, previous, nextImage) {
  if (!preserveView || previous?.mode !== "custom") return null;
  if (previous.naturalW !== nextImage.naturalW || previous.naturalH !== nextImage.naturalH) {
    return null;
  }
  if (![previous.scale, previous.offsetX, previous.offsetY].every(Number.isFinite)) {
    return null;
  }
  return {
    scale: previous.scale,
    offsetX: previous.offsetX,
    offsetY: previous.offsetY,
    mode: "custom",
  };
}
