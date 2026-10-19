// Task-focused, non-linear walkthroughs for each working mode.

import { showModal } from "./modal.js";
import { showAdvancedTutorial } from "./advanced_tutorial.js";

export const GUIDED_TUTORIALS = [
  {
    "id": "transform",
    "title": "Transform",
    "panel": "transform",
    "description": "Correct geometry while keeping supported labels synchronized.",
    "lessons": [
      {
        "id": "transform-geometry",
        "title": "Rotate, shift, scale, and shear",
        "reference": "transform-geometry-crop",
        "outcome": "Commit one reversible geometric correction without accidentally stacking old values.",
        "steps": [
          "Open an image, image folder, or labelled dataset and choose Transform mode.",
          "If labels are present, leave Annotation-aware transform enabled. Use the built-in practice image if you want a safe example.",
          "Adjust rotation, X/Y shift, scale, shear, or flips while watching the live preview.",
          "Choose Apply for the current image or Apply to All only when the same geometry is valid for the collection.",
          "Confirm the controls returned to neutral. Enable Keep settings after Apply only for intentional repeated stacking.",
          "Open History to inspect or undo the exact values that were committed."
        ]
      },
      {
        "id": "transform-perspective",
        "title": "Perspective correction",
        "reference": "transform-perspective",
        "outcome": "Straighten a four-corner plane and retain box, polygon, and mask alignment.",
        "steps": [
          "Start with small corner-coordinate changes and identify which edge needs correction.",
          "Move matching top or bottom corners together before fine-tuning individual corners.",
          "Inspect labelled objects near every edge; out-of-frame annotations are clipped or removed safely.",
          "Apply once, then use Compare and History to verify the result."
        ]
      },
      {
        "id": "transform-crop",
        "title": "Free crop with labels",
        "reference": "transform-geometry-crop",
        "outcome": "Crop visually while updating every supported spatial annotation.",
        "steps": [
          "Choose Free Crop and drag the frame over the region you need.",
          "Resize from an edge or corner; use Cancel if the frame is wrong.",
          "Keep Annotation-aware transform enabled when labels must follow the crop.",
          "Accept the crop, then inspect clipped edge annotations before export."
        ]
      }
    ]
  },
  {
    "id": "augment",
    "title": "Augment",
    "panel": "augment",
    "description": "Create realistic, reproducible training variation.",
    "lessons": [
      {
        "id": "augment-custom",
        "title": "Build a custom augmentation",
        "reference": "augment-color-filters",
        "outcome": "Apply a controlled appearance or geometry variation with no forgotten slider values.",
        "steps": [
          "Open Custom Augmentation and choose only changes that are realistic for the target data.",
          "For geometric controls on labelled images, keep Annotation-aware augmentation enabled.",
          "Preview color, filter, geometry, flip, or padding values before committing.",
          "Apply once and verify that values reset. Keep settings is intentionally off by default.",
          "Use History to verify the category, control, and committed value."
        ]
      },
      {
        "id": "augment-recipes",
        "title": "Generate seeded variants",
        "reference": "seeded-recipes",
        "outcome": "Generate repeatable variants whose sampled settings can be reproduced later.",
        "steps": [
          "Open Seeded Recipes and choose a preset or Custom as a starting point.",
          "Enable only useful transformations and set each Min/Max range or flip chance.",
          "Set Variants per image and a Seed; the same inputs and seed reproduce the same choices.",
          "Check the workspace card: image-only sources create image variants, while labelled datasets keep annotations synchronized.",
          "Generate and inspect the recorded recipe before using the output for training."
        ]
      },
      {
        "id": "augment-safety",
        "title": "Validate annotation awareness",
        "reference": "annotation-awareness",
        "outcome": "See how boxes, polygons, and bitmap masks follow geometric augmentation.",
        "steps": [
          "Open the Augmentation Practice Image from the annotation-safety group.",
          "Try rotation, translation, shear, scale, a flip, and padding with awareness enabled.",
          "Zoom into each geometry type and confirm its overlay follows the image.",
          "Turn awareness off only to understand the warning; do not export misaligned labels for training."
        ]
      }
    ]
  },
  {
    "id": "annotate",
    "title": "Annotate",
    "panel": "annotation",
    "description": "Create and refine classification, detection, segmentation, and pose labels.",
    "lessons": [
      {
        "id": "annotate-boxes",
        "title": "Object-detection boxes",
        "reference": "annotate-create",
        "outcome": "Create, correct, and save accurate bounding boxes.",
        "steps": [
          "Create or import classes, choose Object Detection — box, and select a class.",
          "Press W (or B) immediately—without clicking Draw first—then drag tightly around the object.",
          "Click the box to select it. Drag inside to move it or drag a handle to resize it.",
          "Press Delete or Backspace to remove a selected box; use Undo if needed.",
          "Open Export, choose autosave or manual working-file saving, and confirm the active location."
        ]
      },
      {
        "id": "annotate-segmentation",
        "title": "Polygon and bitmap-mask segmentation",
        "reference": "annotate-create",
        "outcome": "Create detailed segmentation geometry and correct it without losing viewport position.",
        "steps": [
          "Choose polygon or bitmap mask output and select the intended class.",
          "For a polygon, press P, click edge points, and finish with Enter or a double-click.",
          "For a bitmap mask, press M, set brush size, paint, erase corrections, and Finish Mask.",
          "Select the result to move or resize it; bitmap pixels and polygon points scale with the frame.",
          "Zoom and pan as needed—the current viewport stays fixed when the annotation appears or changes."
        ]
      },
      {
        "id": "annotate-pose",
        "title": "Bottom-up and top-down pose estimation",
        "reference": "annotate-create",
        "outcome": "Create ordered, editable pose landmarks for MediaPipe, YOLO Pose, or COCO Keypoints.",
        "steps": [
          "Choose Pose Estimation — keypoints and select the object class.",
          "Choose Bottom-up MediaPipe 33 for points only, or Top-down YOLO/COCO 17 for a box followed by points.",
          "Press K or W. Follow each named landmark; Shift+click marks occluded and Skip Keypoint marks absent.",
          "Select a committed pose and drag an individual dot to correct it; drag the frame or handles to transform the whole pose.",
          "Open Export and select Pose Estimation to see only schema-compatible formats."
        ]
      },
      {
        "id": "annotate-classes",
        "title": "Manage classes and annotation files",
        "reference": "annotate-classes",
        "outcome": "Maintain a clean class list and an explicit save destination.",
        "steps": [
          "Add classes manually or import classes.txt, YOLO YAML, or COCO JSON.",
          "Rename a class and Save it when the semantic label needs correction.",
          "When deleting an in-use class, explicitly move its annotations or delete every annotation using it.",
          "Open Export and choose Save Beside Images or a custom working-file folder.",
          "Select a training task; VisionDB Craft then shows only compatible export formats."
        ]
      }
    ]
  }
];

export function showGuidedTutorials(initialMode = "transform") {
  let activeMode = GUIDED_TUTORIALS.find((mode) => mode.id === initialMode) || GUIDED_TUTORIALS[0];
  let activeLesson = activeMode.lessons[0];
  let modalApi = null;
  const root = document.createElement("div");
  root.className = "guided-guide";
  const modeNav = document.createElement("nav");
  modeNav.className = "guided-mode-nav";
  modeNav.setAttribute("aria-label", "Guided tutorial modes");
  const layout = document.createElement("div");
  layout.className = "guided-layout";
  const lessonNav = document.createElement("nav");
  lessonNav.className = "guided-lesson-nav";
  lessonNav.setAttribute("aria-label", "Guided tutorial lessons");
  const article = document.createElement("article");
  article.className = "guided-article";
  layout.append(lessonNav, article);
  root.append(modeNav, layout);

  function renderModes() {
    modeNav.innerHTML = "";
    for (const mode of GUIDED_TUTORIALS) {
      const choice = document.createElement("button");
      choice.textContent = mode.title;
      choice.classList.toggle("active", mode.id === activeMode.id);
      choice.addEventListener("click", () => {
        activeMode = mode;
        activeLesson = mode.lessons[0];
        render();
      });
      modeNav.append(choice);
    }
  }

  function renderLessons() {
    lessonNav.innerHTML = "";
    const heading = document.createElement("div");
    heading.className = "guided-mode-summary";
    const title = document.createElement("strong");
    title.textContent = activeMode.title;
    const description = document.createElement("span");
    description.textContent = activeMode.description;
    heading.append(title, description);
    lessonNav.append(heading);
    for (const lesson of activeMode.lessons) {
      const choice = document.createElement("button");
      choice.textContent = lesson.title;
      choice.classList.toggle("active", lesson.id === activeLesson.id);
      choice.addEventListener("click", () => {
        activeLesson = lesson;
        renderLessons();
        renderArticle();
      });
      lessonNav.append(choice);
    }
  }

  function renderArticle() {
    article.innerHTML = "";
    const eyebrow = document.createElement("span");
    eyebrow.className = "guided-eyebrow";
    eyebrow.textContent = activeMode.title;
    const title = document.createElement("h2");
    title.textContent = activeLesson.title;
    const outcome = document.createElement("p");
    outcome.className = "guided-outcome";
    outcome.textContent = activeLesson.outcome;
    const actions = document.createElement("div");
    actions.className = "guided-actions";
    const openMode = document.createElement("button");
    openMode.className = "primary";
    openMode.textContent = `Open ${activeMode.title}`;
    openMode.addEventListener("click", () => {
      document.dispatchEvent(new CustomEvent("imagecraft:request-working-mode", {
        detail: { mode: activeMode.id },
      }));
      modalApi?.close();
    });
    const details = document.createElement("button");
    details.textContent = "Open advanced details";
    details.addEventListener("click", () => {
      const topic = activeLesson.reference;
      modalApi?.close();
      window.setTimeout(() => showAdvancedTutorial(topic), 0);
    });
    actions.append(openMode, details);
    const checklist = document.createElement("ol");
    checklist.className = "guided-checklist";
    for (const [index, instruction] of activeLesson.steps.entries()) {
      const item = document.createElement("li");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.id = `guided-${activeLesson.id}-${index}`;
      const label = document.createElement("label");
      label.htmlFor = check.id;
      label.textContent = instruction;
      item.append(check, label);
      checklist.append(item);
    }
    article.append(eyebrow, title, outcome, actions, checklist);
  }

  function render() {
    renderModes();
    renderLessons();
    renderArticle();
  }

  render();
  modalApi = showModal({
    title: "Guided Tutorials",
    content: root,
    className: "guided-tutorial-modal",
  });
  return modalApi;
}
