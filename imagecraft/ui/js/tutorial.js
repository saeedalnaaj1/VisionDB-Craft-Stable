// Interactive tutorial — a modal walkthrough with Previous / Next / Exit.
// Each step can open a sidebar tab and "spotlight" a real UI element so the
// user learns by seeing the actual controls.

import { setActive } from "./sidebar.js";
import { requestWorkingMode } from "./mode_manager.js";
import { state } from "./state.js";

const STEPS = [
  {
    "title": "Welcome to VisionDB Craft",
    "body": "VisionDB Craft is a non-destructive computer-vision image and dataset\n      workbench. Choose <b>Transform</b>, <b>Augment</b>, or <b>Annotate</b> as your focused mode. Resize, Export, History, and\n      Dataset remain shared. This overview follows those workflows in order.",
    "highlight": "#tb-mode"
  },
  {
    "title": "Choose the correct input type",
    "body": "<b>Open Image</b> loads one image for testing. <b>Open Images Folder</b>\n      loads an unlabelled collection. <b>Open Labelled Dataset</b> loads classification,\n      YOLO, COCO or Pascal VOC images, labels, classes and split structure. VisionDB Craft warns\n      you if the selected folder appears to belong to the other workflow.",
    "highlight": "#tb-dataset"
  },
  {
    "title": "Save and resume complete projects",
    "body": "<b>Save Project</b> creates one portable <b>.imagecraft</b> project containing\n      images, annotations, edits, History, current mode, detector proposals, panel\n      state, zoom and pan. <b>Open Project</b> resumes that workspace. If original\n      media moved, the embedded copy remains usable and VisionDB Craft offers relinking.",
    "highlight": "#tb-save-project"
  },
  {
    "title": "Navigate the viewer without losing your place",
    "body": "Zoom with the toolbar, floating controls, mouse wheel, or <b>Ctrl +/−</b>.\n      Pan by dragging empty canvas; use <b>Fit</b> or <b>1:1</b> only when you want\n      to reset the view. Creating, selecting, moving, resizing, deleting, or\n      reclassifying a box, polygon, or mask preserves the exact zoom and pan.\n      <b>A</b> / <b>D</b> browse images.",
    "highlight": "#viewer-tools"
  },
  {
    "title": "Adjust panels and find every shortcut",
    "body": "Drag the inner edge of Controls to resize it; double-click that edge to\n      restore its default width. Dock it left, right, or bottom. The\n      <b>Shortcuts</b> button groups keys by section, including annotation-only\n      drawing keys, so shortcuts do not have to be memorized in advance.",
    "highlight": "#tb-shortcuts"
  },
  {
    "title": "Transform geometry",
    "body": "Transform adjusts translation, rotation, scale, shear, flips, exact edge\n      crop, free crop, and four-corner perspective. Preview first, then choose\n      <b>Apply</b> or <b>Apply to All</b>. Every commit is reversible.",
    "tab": "transform",
    "highlight": "#sidebar"
  },
  {
    "title": "Transform labels safely",
    "body": "<b>Annotation-aware transform</b> is on by default: boxes, polygons, and\n      bitmap masks follow crop, perspective, rotation, translation, scaling,\n      shear, flips, and padding. Turning it off shows a warning before Apply.\n      Use the built-in Transform Practice Image to verify behavior safely. Controls\n      reset after Apply unless intentional repeated stacking is enabled.",
    "tab": "transform",
    "highlight": "#sidebar"
  },
  {
    "title": "Create a custom augmentation",
    "body": "Custom Augmentation provides exact color, filter, noise, geometry, flip,\n      and padding values for training data. <b>Annotation-aware augmentation</b>\n      keeps supported labels synchronized. Applied controls reset by default so a\n      forgotten slider is not silently stacked onto the next effect.",
    "tab": "augment",
    "highlight": "#sidebar"
  },
  {
    "title": "Generate seeded augmentation recipes",
    "body": "Seeded Recipes create controlled variants. Choose a preset or Custom,\n      enable transformations, edit every Min/Max range and flip chance, then set\n      variants per image and a seed. The same inputs, recipe, and seed reproduce\n      the same sampled choices. Labelled datasets produce synchronized annotations;\n      image folders produce image-only variants.",
    "tab": "augment",
    "highlight": "#sidebar"
  },
  {
    "title": "Practise augmentation safely",
    "body": "Open the built-in labelled Augmentation Practice Image to inspect one box,\n      polygon, and bitmap mask under geometric changes. It is the fastest way to\n      learn annotation awareness before processing valuable training data.",
    "tab": "augment",
    "highlight": "#sidebar"
  },
  {
    "title": "Choose an annotation task",
    "body": "Annotate supports whole-image classification, object-detection boxes,\n      polygon and bitmap/RLE segmentation, and pose keypoints. Pose offers\n      bottom-up MediaPipe 33 landmarks without a displayed box or top-down\n      YOLO/COCO 17 landmarks with a box. Choose or create a\n      class first. <b>W</b> starts whichever drawing type is selected; press\n      <b>W</b> again to stop drawing. Direct keys\n      remain available: <b>B</b> for a box, <b>P</b> for a polygon, <b>M</b> for a\n      bitmap mask, <b>K</b> for pose, and <b>C</b> for classification, only in\n      Annotate mode.",
    "tab": "annotation",
    "highlight": "#sidebar"
  },
  {
    "title": "Draw boxes, polygons, and poses",
    "body": "For a box, drag tightly around an object. For a polygon, click edge points\n      and finish with Enter or a double-click. Escape cancels a draft. The shape\n      appears at the same zoom and pan you used while drawing—VisionDB Craft does not\n      jump back to 100%. For pose, follow each named point; Shift+click marks an\n      occluded point and Skip Keypoint records it as unlabelled.",
    "tab": "annotation",
    "highlight": "#sidebar"
  },
  {
    "title": "Paint and edit bitmap masks",
    "body": "Choose <b>Segmentation — bitmap mask</b>, set brush size, and paint the\n      object. Enable Erase to correct edges, then Finish Mask. Select a saved mask\n      and choose Edit Selected Mask to add or erase pixels later. COCO can preserve\n      masks as lossless RLE; PNG instance-mask export writes direct bitmap files.",
    "tab": "annotation",
    "highlight": "#sidebar"
  },
  {
    "title": "Select, move, resize, and delete",
    "body": "Click a box, polygon, or mask to select it; nested geometry chooses the\n      smallest item under the pointer. Drag inside to move it or drag one of eight\n      handles to resize it. Press <b>Delete</b> or <b>Backspace</b> to remove it.\n      These actions enter History and preserve the exact viewport.",
    "tab": "annotation",
    "highlight": "#sidebar"
  },
  {
    "title": "Review annotations on the image",
    "body": "The Annotation log can select, show, hide, reclassify, redraw, or delete\n      each item. Its <b>Show all</b> and <b>Hide all</b> controls manage every row,\n      while <b>Show annotations</b> hides all overlays without deleting labels.\n      Canvas selection and list selection stay synchronized so crowded images can\n      be reviewed precisely.",
    "tab": "annotation",
    "highlight": "#sidebar"
  },
  {
    "title": "Manage and import classes",
    "body": "Add, rename, or delete classes manually, or import classes.txt, YOLO YAML,\n      or COCO JSON. When deleting an in-use class, explicitly choose to move its\n      annotations to another class or delete every annotation using it. One-class\n      mode accelerates repetitive single-class labelling.",
    "tab": "annotation",
    "highlight": "#sidebar"
  },
  {
    "title": "Save annotation files",
    "body": "Open <b>Export</b> to manage all annotation persistence in one place.\n      Auto-save or manually save current/all editable working files beside the images\n      or in one custom folder. These files preserve editing metadata without silently\n      replacing source images or imported labels.",
    "tab": "export",
    "highlight": "#sidebar"
  },
  {
    "title": "Export training annotations",
    "body": "Export detects classification labels, boxes, polygons, masks, and poses, then\n      shows only formats valid for the selected training task. Detection offers YOLO,\n      COCO, and Pascal VOC; segmentation offers COCO, YOLO polygons, and PNG masks;\n      pose offers YOLO Pose, COCO Keypoints, and MediaPipe 33-landmark JSON;\n      classification uses class folders. Mixed tasks are separated explicitly.",
    "tab": "export",
    "highlight": "#sidebar"
  },
  {
    "title": "Resize and export edited images",
    "body": "Resize sets exact dimensions with optional aspect lock and supports one\n      image or the batch. Export controls filename prefix/postfix and save scope:\n      current, modified, or all. Spatial labels remain synchronized through resize.",
    "tab": "resize",
    "highlight": "#sidebar"
  },
  {
    "title": "Use global History and recovery",
    "body": "Undo/Redo and History cover transforms, augmentation, annotation edits,\n      and completed batches. Each row records the\n      section, control, and value. Click an earlier row to undo to it or a future\n      row to redo to it. Reset affects the current image; Reset All affects the\n      collection.",
    "tab": "history",
    "highlight": "#sidebar"
  },
  {
    "title": "Analyze and prepare datasets",
    "body": "Dataset analysis checks missing/orphan labels, invalid geometry, corrupt\n      files, exact and near duplicates, split leakage, tiny objects, and class\n      imbalance, then reports statistics and health. Create reproducible seeded\n      splits, generate annotation-safe variants, or export a clean YOLO, COCO,\n      Pascal VOC, or mask dataset to a new folder.",
    "tab": "dataset",
    "highlight": "#sidebar"
  },
  {
    "title": "You're ready",
    "body": "Use <b>Tutorials</b> whenever you need help: <b>App Overview</b> replays\n      this ordered tour, <b>Advanced</b> searches every control and effect in any\n      order, and <b>Guided</b> offers practical lessons for all three modes. Open an\n      image, folder, dataset, or project and begin—committed work remains reversible.",
    "highlight": "#tb-tutorials"
  }
];

const MODE_FOR_TAB = {
  transform: "transform",
  augment: "augment",
  annotation: "annotate",
  auto_annotate: "auto_annotate",
  local_ai: "ai_annotate",
};

export function showTutorial() {
  let index = 0;
  let spotlit = null;

  const clearSpotlight = () => {
    if (spotlit) {
      spotlit.classList.remove("tutorial-spotlight");
      spotlit = null;
    }
  };

  const applySpotlight = (selector) => {
    clearSpotlight();
    if (!selector) return;
    const el = document.querySelector(selector);
    if (!el) return;
    spotlit = el;
    el.classList.add("tutorial-spotlight");
    try {
      el.scrollIntoView({ block: "nearest", inline: "nearest" });
    } catch (_) { /* older engines */ }
  };

  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop tutorial-backdrop";

  const modal = document.createElement("div");
  modal.className = "modal tutorial-modal";

  const header = document.createElement("div");
  header.className = "modal-header";
  const titleEl = document.createElement("h2");
  titleEl.className = "modal-title";
  titleEl.textContent = "App Overview";
  const closeBtn = document.createElement("button");
  closeBtn.className = "modal-close";
  closeBtn.textContent = "✕";
  closeBtn.title = "Exit tutorial";
  closeBtn.addEventListener("click", close);
  header.append(titleEl, closeBtn);

  const body = document.createElement("div");
  body.className = "modal-body";
  const stepTitle = document.createElement("h3");
  stepTitle.className = "tutorial-step-title";
  const stepText = document.createElement("div");
  stepText.className = "tutorial-step-text";
  body.append(stepTitle, stepText);

  const footer = document.createElement("div");
  footer.className = "tutorial-footer";
  const counter = document.createElement("span");
  counter.className = "tutorial-counter";
  const prevBtn = mkButton("‹ Previous", () => go(-1));
  const nextBtn = mkButton("Next ›", () => go(1));
  const exitBtn = mkButton("Exit", close);
  exitBtn.className = "tutorial-exit";
  const nav = document.createElement("div");
  nav.className = "tutorial-nav";
  nav.append(prevBtn, nextBtn, exitBtn);
  footer.append(counter, nav);

  modal.append(header, body, footer);
  // Keep the dialog in a layer above both the dimmer and the highlighted
  // application control. If it is nested in the backdrop, a large spotlight
  // (notably the viewer in step 8) can cover the dialog with its stacking layer.
  document.body.append(backdrop, modal);

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });
  document.addEventListener("keydown", onKey);

  function mkButton(label, fn) {
    const b = document.createElement("button");
    b.textContent = label;
    b.addEventListener("click", fn);
    return b;
  }

  function onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
  }

  function render() {
    const step = STEPS[index];
    if (step.tab) {
      const mode = MODE_FOR_TAB[step.tab];
      const hasPendingWork = state.hasUnsavedWork
        || Object.values(state.editParams || {}).some((params) => params != null)
        || (state.autoAnnotatePreview?.candidates || []).length > 0;
      if (
        mode
        && (!hasPendingWork || (mode === state.workingMode && step.tab === state.activeTool))
      ) {
        requestWorkingMode(mode).then((switched) => {
          if (switched) setActive(step.tab);
        });
      } else if (!mode && (!hasPendingWork || step.tab === state.activeTool)) {
        setActive(step.tab);
      }
    }
    stepTitle.textContent = step.title;
    stepText.innerHTML = step.body;
    counter.textContent = `Step ${index + 1} of ${STEPS.length}`;
    prevBtn.disabled = index === 0;
    nextBtn.textContent = index === STEPS.length - 1 ? "Finish" : "Next ›";
    applySpotlight(step.highlight);
  }

  function go(delta) {
    if (delta > 0 && index === STEPS.length - 1) { close(); return; }
    index = Math.min(STEPS.length - 1, Math.max(0, index + delta));
    render();
  }

  function close() {
    clearSpotlight();
    document.removeEventListener("keydown", onKey);
    modal.remove();
    backdrop.remove();
  }

  render();
  return { close };
}
