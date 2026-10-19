// One predictable entry point for all learning material.

import { showModal } from "./modal.js";
import { showTutorial } from "./tutorial.js";
import { showAdvancedTutorial } from "./advanced_tutorial.js";
import { showGuidedTutorials } from "./guided_tutorials.js";

const OPTIONS = [
  {
    title: "App Overview",
    description: "A short, ordered tour of the complete VisionDB Craft workflow.",
    action: showTutorial,
  },
  {
    title: "Advanced",
    description: "A searchable, non-linear reference explaining every control and effect.",
    action: showAdvancedTutorial,
  },
  {
    title: "Guided",
    description: "Choose a mode and follow a practical task one step at a time.",
    action: showGuidedTutorials,
  },
];

export function showTutorials() {
  const root = document.createElement("div");
  root.className = "tutorial-hub";
  const intro = document.createElement("p");
  intro.textContent = "Choose the kind of help you need. You can return here at any time without changing your work.";
  const grid = document.createElement("div");
  grid.className = "tutorial-hub-grid";
  let modalApi = null;

  for (const option of OPTIONS) {
    const card = document.createElement("button");
    card.className = "tutorial-hub-card";
    const title = document.createElement("strong");
    title.textContent = option.title;
    const description = document.createElement("span");
    description.textContent = option.description;
    card.append(title, description);
    card.addEventListener("click", () => {
      modalApi?.close();
      window.setTimeout(() => option.action(), 0);
    });
    grid.append(card);
  }
  root.append(intro, grid);
  modalApi = showModal({
    title: "Tutorials",
    content: root,
    className: "tutorial-hub-modal",
  });
  return modalApi;
}
