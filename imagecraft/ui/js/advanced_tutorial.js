// Searchable, non-linear reference for every VisionDB Craft workspace. Unlike the
// guided Tutorial, this browser never forces an order: users choose a topic,
// inspect every control, and can jump directly to the matching panel.

import { showModal } from "./modal.js";
import { setActive } from "./sidebar.js";
import { requestWorkingMode } from "./mode_manager.js";

const c = (name, meaning, effect) => ({ name, meaning, effect });

export const ADVANCED_TOPICS = [
  {
    "id": "inputs",
    "category": "Foundations",
    "title": "Inputs and workspace types",
    "summary": "Choose the correct source so VisionDB Craft knows whether labels and dataset structure must travel with the images.",
    "sections": [
      {
        "title": "Opening content",
        "body": "The three open commands are deliberately separate. Folder detection warns when a choice looks inconsistent, but the final decision remains yours.",
        "controls": [
          {
            "name": "Open Image",
            "meaning": "Loads one image for editing, annotation or detector testing.",
            "effect": "Creates a single-image workspace with no imported label structure."
          },
          {
            "name": "Open Images Folder",
            "meaning": "Loads supported images from an ordinary folder.",
            "effect": "Use for unlabelled collections. If labels are detected, VisionDB Craft offers to reopen it as a dataset."
          },
          {
            "name": "Open Labelled Dataset",
            "meaning": "Loads classification folders, YOLO, COCO or Pascal VOC data.",
            "effect": "Imports classes, labels, splits and task information so geometry changes can keep annotations synchronized."
          },
          {
            "name": "Workspace badge",
            "meaning": "Shows Single Image, Image Collection, Labelled Dataset or No Input.",
            "effect": "Check this before augmentation or export; it tells you whether annotation-aware output is possible."
          }
        ]
      },
      {
        "title": "Source safety",
        "body": "VisionDB Craft edits an in-memory working state. Dataset exports and cleaned copies are written to new locations; source labels are not silently replaced.",
        "controls": [
          {
            "name": "Confirmation prompt",
            "meaning": "Appears when the chosen folder looks like the other input type.",
            "effect": "Prevents labels from being ignored accidentally without blocking an intentional image-only workflow."
          },
          {
            "name": "Close Dataset",
            "meaning": "Closes the current labelled project.",
            "effect": "Ends dataset-specific operations without deleting source files."
          },
          {
            "name": "Recent projects",
            "meaning": "Reopens a previously used dataset path.",
            "effect": "Saves navigation time; the project is re-read from disk."
          }
        ]
      }
    ]
  },
  {
    "id": "modes-projects",
    "category": "Foundations",
    "title": "Focused modes and portable projects",
    "summary": "Keep each workflow understandable while preserving complete work when you pause, resume, or change direction.",
    "sections": [
      {
        "title": "Three focused modes",
        "controls": [
          {
            "name": "Transform",
            "meaning": "Shows geometry correction as the primary panel.",
            "effect": "Resize, Export, History, and Dataset remain available as shared tools."
          },
          {
            "name": "Augment",
            "meaning": "Shows custom and seeded dataset augmentation as the primary panel.",
            "effect": "Keeps dataset variation separate from ordinary image correction."
          },
          {
            "name": "Annotate",
            "meaning": "Shows manual classification, box, polygon, and bitmap-mask tools.",
            "effect": "Use it to create or refine committed training labels."
          },
          {
            "name": "Mode switch protection",
            "meaning": "Appears when the current workspace has unsaved or pending work.",
            "effect": "Choose Save Project, Export, Abandon Work, or Cancel; VisionDB Craft does not silently discard the session."
          }
        ]
      },
      {
        "title": "Portable .imagecraft projects",
        "controls": [
          {
            "name": "Open Project",
            "meaning": "Restores the complete saved workspace instead of importing only source files.",
            "effect": "Returns to the saved mode, edit state, zoom, and pan."
          },
          {
            "name": "Relink missing media",
            "meaning": "Reconnects original files that moved after a project was saved.",
            "effect": "The embedded project copies remain available while paths are repaired."
          },
          {
            "name": "Cancel an opener",
            "meaning": "Closes a file or folder picker without loading anything.",
            "effect": "Preserves the current image, labels, History, and viewport exactly."
          }
        ]
      }
    ]
  },
  {
    "id": "viewer-layout",
    "category": "Foundations",
    "title": "Viewer, navigation and panel layout",
    "summary": "Control how the image is displayed without changing its pixels.",
    "sections": [
      {
        "title": "Canvas navigation",
        "controls": [
          {
            "name": "Mouse wheel",
            "meaning": "Zooms around the pointer position.",
            "effect": "Inspect an exact region without losing your place."
          },
          {
            "name": "Fit",
            "meaning": "Fits the complete image inside the viewer.",
            "effect": "Best overview after zooming or switching images."
          },
          {
            "name": "1:1",
            "meaning": "Displays one image pixel per screen pixel.",
            "effect": "Useful for judging blur, noise, masks and fine edges."
          },
          {
            "name": "Compare",
            "meaning": "Shows original and current edited image together.",
            "effect": "Verifies visual edits; it is available after pixel modifications."
          },
          {
            "name": "Annotation viewport preservation",
            "meaning": "Keeps custom zoom and pan while a box, polygon, or mask is created or edited.",
            "effect": "The view resets only when you choose Fit, 1:1, or open a different image."
          }
        ]
      },
      {
        "title": "Controls panel",
        "controls": [
          {
            "name": "Panels",
            "meaning": "Collapses or expands the controls sidebar.",
            "effect": "Gives the image more room without losing work."
          },
          {
            "name": "Inner resize edge",
            "meaning": "Drag to make a left/right sidebar wider or narrower; double-click resets it.",
            "effect": "Prevents long tab names and controls from feeling cramped."
          },
          {
            "name": "Dock button",
            "meaning": "Cycles the controls between right, left and bottom.",
            "effect": "Adapts the workspace to screen shape and preference."
          },
          {
            "name": "Live",
            "meaning": "Updates the canvas while controls change.",
            "effect": "Turn it off on slower systems and use Preview manually when desired."
          },
          {
            "name": "Perf: High / Low",
            "meaning": "Selects the preview performance profile.",
            "effect": "High uses available acceleration and a larger preview; Low reduces work for modest hardware."
          }
        ]
      }
    ]
  },
  {
    "id": "annotation-awareness",
    "category": "Foundations",
    "title": "Annotation-aware image editing",
    "summary": "Keep boxes, polygons, and bitmap/RLE masks aligned whenever pixels move geometrically.",
    "sections": [
      {
        "title": "Safety controls",
        "controls": [
          {
            "name": "Annotation-aware transform",
            "meaning": "Transforms supported labels with crop, perspective, rotation, translation, scale, shear, flips, and padding.",
            "effect": "Enabled by default so labelled data stays usable for training."
          },
          {
            "name": "Annotation-aware augmentation",
            "meaning": "Applies the same geometric augmentation to image pixels and supported labels.",
            "effect": "Works for Custom Augmentation and generated seeded variants."
          },
          {
            "name": "Warning when disabled",
            "meaning": "Requires deliberate confirmation before a geometric Apply with labels present.",
            "effect": "Prevents accidental export of visibly misaligned training annotations."
          },
          {
            "name": "Transform Practice Image",
            "meaning": "Opens a built-in labelled image containing a box, polygon, and RLE mask.",
            "effect": "Lets you validate every transform without risking real data."
          },
          {
            "name": "Augmentation Practice Image",
            "meaning": "Opens the equivalent built-in example in Augment mode.",
            "effect": "Demonstrates annotation-safe rotation, shift, scale, shear, flips, and padding."
          }
        ]
      },
      {
        "title": "Geometry outcomes",
        "controls": [
          {
            "name": "Clipping",
            "meaning": "Limits transformed geometry to the new image bounds.",
            "effect": "Partly visible labels are clipped; fully out-of-frame labels are removed."
          },
          {
            "name": "Boxes",
            "meaning": "Transforms corners and encloses the visible result.",
            "effect": "Produces valid detection boxes after geometric editing."
          },
          {
            "name": "Polygons",
            "meaning": "Transforms every polygon point.",
            "effect": "Preserves detailed segmentation outlines where possible."
          },
          {
            "name": "Bitmap/RLE masks",
            "meaning": "Decodes, warps, clips, and re-encodes mask pixels.",
            "effect": "Maintains pixel-level segmentation rather than reducing masks to boxes."
          }
        ]
      }
    ]
  },
  {
    "id": "transform-perspective",
    "category": "Transform",
    "title": "Perspective",
    "panel": "transform",
    "summary": "Warp the four image corners independently to correct or create perspective.",
    "sections": [
      {
        "title": "Corner coordinates",
        "body": "Coordinates are measured in pixels of the active image. X grows from left to right and Y grows from top to bottom.",
        "controls": [
          {
            "name": "Top-Left X / Y",
            "meaning": "Sets the destination of the upper-left corner.",
            "effect": "Move inward to taper that side; move vertically to tilt the top edge."
          },
          {
            "name": "Top-Right X / Y",
            "meaning": "Sets the destination of the upper-right corner.",
            "effect": "Works with Top-Left to straighten or slant the top plane."
          },
          {
            "name": "Bottom-Right X / Y",
            "meaning": "Sets the destination of the lower-right corner.",
            "effect": "Changes lower-right convergence and floor/base alignment."
          },
          {
            "name": "Bottom-Left X / Y",
            "meaning": "Sets the destination of the lower-left corner.",
            "effect": "Works with Bottom-Right to straighten or slant the bottom plane."
          }
        ]
      },
      {
        "title": "Using perspective safely",
        "body": "Start with small movements and watch the live preview. Existing boxes, polygons and masks are transformed with the image; annotations clipped completely outside are removed.",
        "controls": [
          {
            "name": "Reset sliders",
            "meaning": "Returns all Transform values to the current image defaults.",
            "effect": "Clears an unwanted preview without altering committed History."
          },
          {
            "name": "Apply",
            "meaning": "Commits the warp to the current image.",
            "effect": "Creates one undoable History event."
          },
          {
            "name": "Apply to All",
            "meaning": "Commits the same coordinate settings to every open image.",
            "effect": "Use only when images share compatible dimensions and camera geometry."
          }
        ]
      }
    ]
  },
  {
    "id": "transform-geometry-crop",
    "category": "Transform",
    "title": "Geometry, crop and Apply behavior",
    "panel": "transform",
    "summary": "Translate, rotate, scale or crop while keeping supported annotations aligned.",
    "sections": [
      {
        "title": "Geometry controls",
        "controls": [
          {
            "name": "X Shift",
            "meaning": "Moves pixels horizontally in pixels.",
            "effect": "Positive values move right; negative values move left."
          },
          {
            "name": "Y Shift",
            "meaning": "Moves pixels vertically in pixels.",
            "effect": "Positive values move down; negative values move up."
          },
          {
            "name": "Rotation °",
            "meaning": "Rotates around the image center.",
            "effect": "Changes image bounds and rotates spatial annotations with it."
          },
          {
            "name": "Scale %",
            "meaning": "Resizes content around its center inside the transform.",
            "effect": "100% is unchanged; below 100 shrinks, above 100 enlarges."
          }
        ]
      },
      {
        "title": "Cropping",
        "controls": [
          {
            "name": "Top / Bottom / Left / Right",
            "meaning": "Trims an exact number of pixels from each edge.",
            "effect": "Useful for consistent batch trimming."
          },
          {
            "name": "Free Crop",
            "meaning": "Opens a draggable crop frame over the image.",
            "effect": "Use for a visual one-off crop."
          },
          {
            "name": "Reset crop frame",
            "meaning": "Restores the free-crop frame to the complete image.",
            "effect": "Lets you restart the selection without leaving crop mode."
          },
          {
            "name": "Accept",
            "meaning": "Commits the selected free-crop rectangle.",
            "effect": "Creates an undoable transform and updates annotations."
          },
          {
            "name": "Cancel",
            "meaning": "Leaves free-crop mode without applying.",
            "effect": "Preserves the current image state."
          }
        ]
      },
      {
        "title": "Commit controls",
        "controls": [
          {
            "name": "Preview",
            "meaning": "Renders current settings without committing them.",
            "effect": "Useful when Live is off."
          },
          {
            "name": "Apply",
            "meaning": "Commits to the current image.",
            "effect": "Adds one History entry."
          },
          {
            "name": "Apply to All",
            "meaning": "Commits to every open image as one batch action.",
            "effect": "The complete batch can be undone together."
          },
          {
            "name": "Keep settings after Apply",
            "meaning": "Leaves values in place after a commit.",
            "effect": "Off by default to prevent accidental duplicate transforms; enable only for intentional repeated stacking."
          }
        ]
      }
    ]
  },
  {
    "id": "augment-color-filters",
    "category": "Augment",
    "title": "Custom augmentation: color and filters",
    "panel": "augment",
    "summary": "Create controlled training variation with explicit values rather than random recipes.",
    "sections": [
      {
        "title": "Color",
        "controls": [
          {
            "name": "White balance",
            "meaning": "Shifts the image between cooler and warmer color balance.",
            "effect": "Simulates illumination or camera color-temperature variation."
          },
          {
            "name": "Hue",
            "meaning": "Rotates colors around the HSV hue wheel.",
            "effect": "Useful for color robustness; avoid it when color defines the class."
          },
          {
            "name": "Saturation",
            "meaning": "Reduces or increases color intensity.",
            "effect": "Simulates faded or vivid capture conditions."
          },
          {
            "name": "Brightness",
            "meaning": "Adjusts the HSV value channel.",
            "effect": "Changes overall lightness without using exposure stops."
          },
          {
            "name": "Exposure",
            "meaning": "Scales light using photographic stops from −2 to +2.",
            "effect": "Models under- and over-exposure; one positive stop is a strong increase."
          }
        ]
      },
      {
        "title": "Filters",
        "controls": [
          {
            "name": "Blur",
            "meaning": "Applies Gaussian blur.",
            "effect": "Models focus loss or motion/optical softness; high values can erase small labels."
          },
          {
            "name": "Softness",
            "meaning": "Reduces local contrast more gently than blur.",
            "effect": "Models smoother optics or compression without as much edge displacement."
          },
          {
            "name": "Sharpen",
            "meaning": "Increases edge contrast.",
            "effect": "Models in-camera sharpening; excess strength can create halos."
          },
          {
            "name": "Oil paint",
            "meaning": "Creates region-based painterly smoothing.",
            "effect": "A strong appearance augmentation; use only if plausible for the training domain."
          },
          {
            "name": "Noise",
            "meaning": "Adds continuous random sensor-like noise.",
            "effect": "Improves robustness to grain and low-quality sensors."
          },
          {
            "name": "Salt & pepper",
            "meaning": "Adds isolated black and white pixels.",
            "effect": "Models impulse noise, dead pixels or transmission errors."
          }
        ]
      }
    ]
  },
  {
    "id": "augment-geometry-actions",
    "category": "Augment",
    "title": "Custom augmentation: geometry, padding and actions",
    "panel": "augment",
    "summary": "Apply dataset-oriented geometric variation while guarding against accidental repeated effects.",
    "sections": [
      {
        "title": "Geometry and flips",
        "controls": [
          {
            "name": "Rotation °",
            "meaning": "Rotates within −180° to +180°.",
            "effect": "Updates supported spatial annotations; choose realistic angles for the use case."
          },
          {
            "name": "Shift px",
            "meaning": "Translates content by a pixel amount.",
            "effect": "Simulates framing changes and object position variation."
          },
          {
            "name": "Scale %",
            "meaning": "Random-access scale control from 50% to 150%.",
            "effect": "Simulates distance/size variation."
          },
          {
            "name": "Shear °",
            "meaning": "Slants the image along an axis.",
            "effect": "Models viewpoint skew; large values distort object shape."
          },
          {
            "name": "Flip up-down",
            "meaning": "Mirrors vertically.",
            "effect": "Use only when upside-down examples remain semantically valid."
          },
          {
            "name": "Flip left-right",
            "meaning": "Mirrors horizontally.",
            "effect": "Common for symmetric tasks; avoid when direction or text matters."
          }
        ]
      },
      {
        "title": "Padding and commit",
        "controls": [
          {
            "name": "Add padding",
            "meaning": "Enables a target canvas size.",
            "effect": "Places the image inside a larger frame instead of stretching it."
          },
          {
            "name": "Width px / Height px",
            "meaning": "Sets the padded output dimensions.",
            "effect": "Must be large enough for the active content."
          },
          {
            "name": "Apply / Apply to All",
            "meaning": "Commits current settings to one image or the whole collection.",
            "effect": "Each commit is undoable; a batch is one History event."
          },
          {
            "name": "Reset sliders",
            "meaning": "Restores neutral augmentation values.",
            "effect": "Clears the pending preview."
          },
          {
            "name": "Keep settings after Apply",
            "meaning": "Retains the values after applying.",
            "effect": "Off by default so a forgotten old slider is not applied again with the next augmentation."
          }
        ]
      }
    ]
  },
  {
    "id": "seeded-recipes",
    "category": "Augment",
    "title": "Seeded augmentation recipes",
    "panel": "augment",
    "summary": "Generate reproducible image variants by sampling enabled ranges from a known seed.",
    "sections": [
      {
        "title": "Recipe selection",
        "body": "Balanced robustness, Low-light resilience, Geometry robustness and Blur/clarity variation are editable starting points. Custom begins without a preset assumption.",
        "controls": [
          {
            "name": "Recipe",
            "meaning": "Selects a built-in starting range set or Custom.",
            "effect": "Loading a preset populates the editor; you remain free to change every range."
          },
          {
            "name": "On",
            "meaning": "Includes or excludes one transformation.",
            "effect": "Unchecked transformations are guaranteed not to be sampled."
          },
          {
            "name": "Min / Max",
            "meaning": "Defines the inclusive sampling range for each enabled transformation.",
            "effect": "Every generated image receives a deterministic value inside that range."
          },
          {
            "name": "Flip chance %",
            "meaning": "Defines probability instead of a numeric range.",
            "effect": "0 never flips, 100 always flips, and the same seed repeats the same choices."
          },
          {
            "name": "Reset to selected preset",
            "meaning": "Restores the original values of the selected built-in recipe.",
            "effect": "Discards temporary editor changes for that preset."
          }
        ]
      },
      {
        "title": "Generation",
        "controls": [
          {
            "name": "Variants / image",
            "meaning": "Sets how many generated copies to make for every source image, from 1 to 10.",
            "effect": "Output count equals source images multiplied by this value."
          },
          {
            "name": "Seed",
            "meaning": "Initializes deterministic random sampling.",
            "effect": "The same source order, recipe ranges and seed reproduce the same parameters."
          },
          {
            "name": "Generate Augmented Images",
            "meaning": "Creates image-only variants for a single image or unlabelled collection.",
            "effect": "No annotation files are invented."
          },
          {
            "name": "Generate Annotated Variants",
            "meaning": "Creates variants while transforming imported labels.",
            "effect": "Available in a labelled dataset; classes and split information are retained."
          },
          {
            "name": "Workspace context card",
            "meaning": "States whether the current input is image-only or labelled.",
            "effect": "Read it before generating so you know exactly what metadata the output can contain."
          }
        ]
      },
      {
        "title": "Available sampled transformations",
        "controls": [
          {
            "name": "Color ranges",
            "meaning": "White balance, hue, saturation, brightness and exposure.",
            "effect": "Models lighting and camera color variation."
          },
          {
            "name": "Filter ranges",
            "meaning": "Blur, softness, sharpen, oil paint, noise and salt & pepper.",
            "effect": "Models image-quality variation."
          },
          {
            "name": "Geometry ranges",
            "meaning": "Rotation, shift, scale and shear.",
            "effect": "Changes spatial layout and updates supported annotations."
          },
          {
            "name": "Flip probabilities",
            "meaning": "Horizontal and vertical flip chances.",
            "effect": "Adds discrete orientation variation under explicit user control."
          }
        ]
      }
    ]
  },
  {
    "id": "resize",
    "category": "Resize & Save",
    "title": "Resize",
    "panel": "resize",
    "summary": "Set exact output dimensions for one image or the complete open collection.",
    "sections": [
      {
        "title": "Dimensions",
        "controls": [
          {
            "name": "Width px",
            "meaning": "Sets target pixel width between 1 and 20,000.",
            "effect": "Changing it also updates height when aspect lock is on."
          },
          {
            "name": "Height px",
            "meaning": "Sets target pixel height between 1 and 20,000.",
            "effect": "Changing it also updates width when aspect lock is on."
          },
          {
            "name": "Lock aspect ratio",
            "meaning": "Preserves the current width-to-height ratio.",
            "effect": "Prevents stretching; turn it off only when an exact non-proportional size is required."
          },
          {
            "name": "Current dimensions",
            "meaning": "Displays the active image size.",
            "effect": "Provides a reference before downscaling or enlarging."
          },
          {
            "name": "Apply / Apply to All",
            "meaning": "Commits the dimensions to one image or every image.",
            "effect": "Spatial annotations remain normalized and aligned; the action is undoable."
          }
        ]
      }
    ]
  },
  {
    "id": "image-export",
    "category": "Resize & Save",
    "title": "Image saving and filename options",
    "panel": "export",
    "summary": "Save edited images with predictable names and a clear choice between changed files and the complete session.",
    "sections": [
      {
        "title": "Naming",
        "controls": [
          {
            "name": "Prefix",
            "meaning": "Adds text before each original filename.",
            "effect": "Useful for identifying a batch or experiment."
          },
          {
            "name": "Postfix",
            "meaning": "Adds text after the base filename and before its extension.",
            "effect": "Useful for versions such as _augmented or _v2."
          },
          {
            "name": "Filename example",
            "meaning": "Previews the combined name.",
            "effect": "Catches naming mistakes before a batch save."
          }
        ]
      },
      {
        "title": "Save scope",
        "controls": [
          {
            "name": "Save Current Image",
            "meaning": "Writes only the active image.",
            "effect": "Uses the selected destination and does not process the rest of the collection."
          },
          {
            "name": "Save Modified",
            "meaning": "Writes images whose pixels were changed.",
            "effect": "Skips untouched images."
          },
          {
            "name": "Save All",
            "meaning": "Writes every image in the current session.",
            "effect": "Includes untouched originals and edited images."
          },
          {
            "name": "Toolbar Save buttons",
            "meaning": "Provide the same common save scopes from any panel.",
            "effect": "Ctrl+S, Ctrl+Shift+S and Ctrl+Shift+A are their keyboard equivalents."
          }
        ]
      }
    ]
  },
  {
    "id": "history",
    "category": "History",
    "title": "Undo, redo and non-linear History",
    "panel": "history",
    "summary": "Inspect committed operations and jump directly to an earlier or later state.",
    "sections": [
      {
        "title": "Timeline behavior",
        "controls": [
          {
            "name": "Highlighted row",
            "meaning": "Marks the current state.",
            "effect": "Everything below it in a dimmed style is currently on the redo branch."
          },
          {
            "name": "Click earlier row",
            "meaning": "Undoes directly to that state.",
            "effect": "Equivalent to repeating Undo until the chosen point."
          },
          {
            "name": "Click dimmed later row",
            "meaning": "Redoes directly to that state.",
            "effect": "Equivalent to repeating Redo until the chosen point."
          },
          {
            "name": "New edit after undo",
            "meaning": "Creates a new branch and discards the dimmed future branch.",
            "effect": "This is standard non-linear editor behavior."
          },
          {
            "name": "History limit",
            "meaning": "Keeps the latest 20 operations in memory.",
            "effect": "An Earlier state label means older steps were dropped to control memory use."
          }
        ]
      },
      {
        "title": "Preview versus History",
        "body": "Live slider previews are temporary. Apply creates a reversible operation.",
        "controls": []
      }
    ]
  },
  {
    "id": "annotate-create",
    "category": "Annotate",
    "title": "Creating annotations",
    "panel": "export",
    "summary": "Create classification, detection, segmentation, and pose labels manually.",
    "sections": [
      {
        "title": "Annotation types",
        "controls": [
          {
            "name": "Object Detection — box",
            "meaning": "Creates an axis-aligned bounding box by dragging.",
            "effect": "Best when training expects rectangular object locations."
          },
          {
            "name": "Segmentation — polygon",
            "meaning": "Creates a multi-point object outline.",
            "effect": "Click each edge point, then double-click or press Enter/Finish Polygon."
          },
          {
            "name": "Segmentation — bitmap mask",
            "meaning": "Paints exact foreground pixels.",
            "effect": "Best for irregular boundaries; finish explicitly after painting."
          },
          {
            "name": "Pose Estimation — keypoints",
            "meaning": "Creates one ordered landmark instance.",
            "effect": "Choose bottom-up MediaPipe 33 points or top-down YOLO/COCO 17 points with a box."
          },
          {
            "name": "Bottom-up · MediaPipe 33",
            "meaning": "Places landmarks directly without drawing an object box.",
            "effect": "Best for landmark-first workflows; VisionDB Craft keeps only an internal selection boundary."
          },
          {
            "name": "Top-down · YOLO Pose / COCO 17",
            "meaning": "Draws the instance box first and then places 17 ordered landmarks.",
            "effect": "Matches box-plus-keypoint pose training pipelines."
          },
          {
            "name": "Classification — whole image",
            "meaning": "Assigns a class to the complete image.",
            "effect": "Has no moveable geometry."
          },
          {
            "name": "Class selector",
            "meaning": "Chooses the semantic class for the new annotation.",
            "effect": "VisionDB Craft does not guess a class."
          }
        ]
      },
      {
        "title": "Drawing controls",
        "controls": [
          {
            "name": "W",
            "meaning": "Toggles the currently selected annotation drawing type on or off.",
            "effect": "Works with box, polygon, bitmap mask, and pose; the second press stops the draft."
          },
          {
            "name": "Draw Box / B",
            "meaning": "Selects and starts box drawing only in Annotate.",
            "effect": "Drag across the object and release."
          },
          {
            "name": "Draw Polygon / P",
            "meaning": "Starts point-by-point polygon drawing.",
            "effect": "Use enough points to follow the boundary without excessive detail."
          },
          {
            "name": "Paint Mask / M",
            "meaning": "Starts bitmap-mask painting.",
            "effect": "Drag one or more brush strokes over the foreground."
          },
          {
            "name": "Place Pose / K",
            "meaning": "Starts the selected pose workflow.",
            "effect": "Follow the named landmark order shown above the canvas."
          },
          {
            "name": "Shift+click",
            "meaning": "Places the current pose point as labelled but occluded.",
            "effect": "Exports visibility 1; a normal click exports visibility 2."
          },
          {
            "name": "Skip Keypoint",
            "meaning": "Records the current landmark as absent or unlabelled.",
            "effect": "Exports x=0, y=0, visibility=0 without changing landmark order."
          },
          {
            "name": "Undo Point",
            "meaning": "Removes the most recently placed draft point.",
            "effect": "Lets you correct the sequence before committing the pose."
          },
          {
            "name": "Brush size",
            "meaning": "Sets mask brush diameter in image pixels.",
            "effect": "Use a large brush for interiors and a small brush near edges."
          },
          {
            "name": "Erase from mask",
            "meaning": "Changes mask strokes from add to subtract.",
            "effect": "Corrects overshoot before finishing or while editing an existing mask."
          },
          {
            "name": "Finish Polygon / Finish Mask / Finish Pose / Enter",
            "meaning": "Commits the active spatial draft.",
            "effect": "Creates an undoable annotation event."
          },
          {
            "name": "Cancel Drawing / Esc",
            "meaning": "Discards the current draft.",
            "effect": "Does not modify annotations or History."
          }
        ]
      }
    ]
  },
  {
    "id": "annotate-edit",
    "category": "Annotate",
    "title": "Selecting, moving, resizing and reviewing",
    "panel": "annotation",
    "summary": "Correct existing boxes, polygons, masks, and poses instead of redrawing work unnecessarily.",
    "sections": [
      {
        "title": "Canvas editing",
        "controls": [
          {
            "name": "Click shape",
            "meaning": "Selects the smallest visible annotation under the pointer.",
            "effect": "The selected shape receives a dashed outline and resize handles."
          },
          {
            "name": "Drag selected shape",
            "meaning": "Moves its complete geometry.",
            "effect": "Polygon points and mask pixels move with their frame."
          },
          {
            "name": "Drag a resize handle",
            "meaning": "Resizes from an edge or corner.",
            "effect": "Polygon points and bitmap-mask pixels scale with the new frame."
          },
          {
            "name": "Delete / Backspace",
            "meaning": "Deletes the selected committed annotation.",
            "effect": "The deletion enters History and can be undone."
          },
          {
            "name": "Redraw Selected",
            "meaning": "Replaces box or polygon geometry with a fresh drawing.",
            "effect": "Keeps its class while replacing location/shape."
          },
          {
            "name": "Edit Selected Mask",
            "meaning": "Loads the existing mask for paint/erase correction.",
            "effect": "Commits a replacement mask when finished."
          },
          {
            "name": "Drag pose keypoint",
            "meaning": "Moves one selected landmark without disturbing the others.",
            "effect": "The change is autosaved and enters History with the landmark name."
          },
          {
            "name": "Redraw Selected Pose",
            "meaning": "Rebuilds the complete ordered landmark instance.",
            "effect": "Use when many points or the top-down box are incorrect."
          }
        ]
      },
      {
        "title": "Annotation log and review",
        "controls": [
          {
            "name": "Visibility checkbox",
            "meaning": "Shows or hides one annotation on the canvas.",
            "effect": "Display-only; it does not delete or exclude the label from export."
          },
          {
            "name": "Show all / Hide all",
            "meaning": "Changes visibility for every row in the current image.",
            "effect": "Useful for isolating crowded or overlapping annotations quickly."
          },
          {
            "name": "Class dropdown",
            "meaning": "Changes the selected annotation's class.",
            "effect": "Creates an undoable reclassification."
          },
          {
            "name": "× / Delete Selected",
            "meaning": "Removes one annotation.",
            "effect": "The same reversible operation as the Delete key."
          },
          {
            "name": "Show annotations",
            "meaning": "Shows or hides all overlays.",
            "effect": "Useful for inspecting the raw image; annotations remain stored."
          },
          {
            "name": "Mark Reviewed",
            "meaning": "Clears the Needs review flag after inspection.",
            "effect": "Does not change geometry or class and is itself undoable."
          }
        ]
      }
    ]
  },
  {
    "id": "annotate-classes",
    "category": "Annotate",
    "title": "Class management",
    "panel": "annotation",
    "summary": "Build, import and safely change the class list used by manual and automatic annotation.",
    "sections": [
      {
        "title": "Class controls",
        "controls": [
          {
            "name": "New class name / Add Class",
            "meaning": "Appends one manually entered class.",
            "effect": "Its numeric ID is its position in the list."
          },
          {
            "name": "Import TXT / YAML / COCO",
            "meaning": "Reads names from classes.txt, YOLO data YAML or COCO categories.",
            "effect": "Adds imported names without requiring manual retyping."
          },
          {
            "name": "Name field / Save",
            "meaning": "Renames an existing class.",
            "effect": "Updates labels that use that class ID."
          },
          {
            "name": "Used count",
            "meaning": "Shows how many current annotations reference the class.",
            "effect": "Explains why deletion may require a migration choice."
          },
          {
            "name": "Move annotations on delete",
            "meaning": "Reassigns every use to another existing class, then deletes the class.",
            "effect": "Preserves annotations while reindexing class IDs safely."
          },
          {
            "name": "Delete all annotations on delete",
            "meaning": "Explicitly removes every annotation using the class.",
            "effect": "Use only when those labels are unwanted; confirmation is required."
          },
          {
            "name": "Delete",
            "meaning": "Deletes the class using the selected handling rule.",
            "effect": "At least one class remains available so drawing cannot become permanently disabled."
          }
        ]
      },
      {
        "title": "Fast repeated labelling",
        "controls": [
          {
            "name": "1 class mode",
            "meaning": "Uses one selected default class repeatedly.",
            "effect": "Reduces class selection steps for single-class datasets."
          },
          {
            "name": "Default class selector",
            "meaning": "Stores the class used by 1 class mode.",
            "effect": "Change it when moving to a different repetitive labelling pass."
          }
        ]
      }
    ]
  },
  {
    "id": "annotate-storage-export",
    "category": "Annotate",
    "title": "Annotation files, save locations and export",
    "panel": "export",
    "summary": "Choose when working annotations are saved and how a standards-based training dataset is exported.",
    "sections": [
      {
        "title": "Working annotation files",
        "controls": [
          {
            "name": "Auto-save working annotation files",
            "meaning": "Writes each committed manual or automatic annotation change.",
            "effect": "Keeps editable VisionDB Craft files current; disable for deliberate manual saving."
          },
          {
            "name": "Save Current / Save All",
            "meaning": "Writes editable annotations for the selected scope.",
            "effect": "Use when autosave is off or before external inspection."
          },
          {
            "name": "Choose Folder",
            "meaning": "Uses one custom directory for VisionDB Craft working annotation files.",
            "effect": "The active destination is highlighted."
          },
          {
            "name": "Save Beside Images",
            "meaning": "Stores VisionDB Craft annotation files near their source images.",
            "effect": "Returns to the default per-image location; the active option is highlighted."
          }
        ]
      },
      {
        "title": "Dataset export",
        "controls": [
          {
            "name": "Choose Export Folder",
            "meaning": "Reuses one parent destination for annotated dataset exports.",
            "effect": "The active option is highlighted."
          },
          {
            "name": "Ask Every Time",
            "meaning": "Prompts for a destination on each export.",
            "effect": "Best when outputs go to different experiments or drives."
          },
          {
            "name": "Training task",
            "meaning": "Separates classification, detection, segmentation, and pose.",
            "effect": "Prevents incompatible annotation types from being mixed into one training label set."
          },
          {
            "name": "YOLO Detection",
            "meaning": "Exports normalized class and box rows.",
            "effect": "Shown only for object detection."
          },
          {
            "name": "YOLO Segmentation",
            "meaning": "Exports class and polygon vertices.",
            "effect": "Shown only for segmentation; bitmap masks are traced to polygons."
          },
          {
            "name": "COCO",
            "meaning": "Exports boxes or instance segmentations according to the selected task.",
            "effect": "Recommended for lossless bitmap-mask preservation through RLE."
          },
          {
            "name": "Pascal VOC",
            "meaning": "Exports per-image XML bounding boxes.",
            "effect": "Shown only for object detection."
          },
          {
            "name": "PNG instance masks",
            "meaning": "Writes one binary mask per object plus a JSON index.",
            "effect": "Shown only for segmentation and preserves raster masks."
          },
          {
            "name": "Class folders",
            "meaning": "Places images under split/class directories.",
            "effect": "Shown only for image classification and works with common classification loaders."
          },
          {
            "name": "YOLO Pose",
            "meaning": "Exports class, normalized box, and ordered x/y/visibility triplets plus data.yaml.",
            "effect": "Shown for a single consistent pose schema; includes kpt_shape, flip_idx, and keypoint names."
          },
          {
            "name": "COCO Keypoints",
            "meaning": "Exports boxes, pixel keypoint triplets, num_keypoints, and category skeleton metadata.",
            "effect": "Safe standard option for keypoint-instance datasets."
          },
          {
            "name": "MediaPipe 33-landmark JSON",
            "meaning": "Exports normalized x/y/z/visibility/presence landmark records.",
            "effect": "Shown only when the selected scope contains the MediaPipe 33 schema."
          },
          {
            "name": "Export Training Dataset",
            "meaning": "Creates a new uniquely named dataset folder.",
            "effect": "Does not overwrite source files and reports annotations excluded because they belong to another task."
          }
        ]
      }
    ]
  },
  {
    "id": "dataset-health",
    "category": "Dataset",
    "title": "Dataset project, health and statistics",
    "panel": "dataset",
    "summary": "Inspect a labelled dataset before spending time on augmentation or model training.",
    "sections": [
      {
        "title": "Project controls",
        "controls": [
          {
            "name": "Open Labelled Dataset",
            "meaning": "Uses the main format-aware dataset opener.",
            "effect": "Loads classes, annotations and split structure."
          },
          {
            "name": "Recent projects",
            "meaning": "Reopens a known dataset path.",
            "effect": "Avoids browsing repeatedly."
          },
          {
            "name": "Close Dataset",
            "meaning": "Ends the labelled project session.",
            "effect": "Does not remove or rewrite source data."
          },
          {
            "name": "Project summary",
            "meaning": "Shows format, image count, class count and generated count.",
            "effect": "Confirms the active dataset before operations."
          }
        ]
      },
      {
        "title": "Health analysis",
        "controls": [
          {
            "name": "Analyze Dataset",
            "meaning": "Runs validation and statistics together.",
            "effect": "Checks missing/orphan labels, invalid classes or geometry, corrupt images, duplicates, split leakage, tiny objects and imbalance."
          },
          {
            "name": "Cancel current operation",
            "meaning": "Requests safe cancellation of a long batch operation.",
            "effect": "Stops at a safe boundary without deleting source data."
          },
          {
            "name": "Health score",
            "meaning": "Summarizes detected errors and warnings on a 0–100 scale.",
            "effect": "Use the individual issue rows for decisions; the score is a high-level signal."
          },
          {
            "name": "Images / Objects / Classes / Empty",
            "meaning": "Displays core dataset counts.",
            "effect": "Highlights unexpected empty images or object totals."
          },
          {
            "name": "Class distribution",
            "meaning": "Shows per-class object counts.",
            "effect": "Reveals imbalance and absent classes."
          },
          {
            "name": "Split distribution",
            "meaning": "Shows image counts per split.",
            "effect": "Reveals missing or disproportionate train/validation/test groups."
          },
          {
            "name": "Issue list",
            "meaning": "Shows severity, issue code, explanation and affected file.",
            "effect": "The complete report is included in export even when the panel shows only the first 50."
          },
          {
            "name": "Export Cleaned Copy",
            "meaning": "Creates a new dataset omitting unsafe records.",
            "effect": "Never mutates the source dataset."
          }
        ]
      }
    ]
  },
  {
    "id": "dataset-split-export",
    "category": "Dataset",
    "title": "Dataset split, augmentation and conversion",
    "panel": "dataset",
    "summary": "Create repeatable splits, generate annotation-safe variants and export a training-ready copy.",
    "sections": [
      {
        "title": "Reproducible split",
        "controls": [
          {
            "name": "Train / Validation / Test %",
            "meaning": "Defines the desired split proportions.",
            "effect": "Values must form a complete split; class-aware assignment attempts to preserve representation."
          },
          {
            "name": "Seed",
            "meaning": "Controls deterministic split assignment.",
            "effect": "The same dataset and seed reproduce the same assignment."
          },
          {
            "name": "Assign Splits",
            "meaning": "Stores the new in-session split labels.",
            "effect": "Source folders are not moved; output structure is written during export."
          }
        ]
      },
      {
        "title": "Augmentation and export",
        "controls": [
          {
            "name": "Open Augmentation Recipes",
            "meaning": "Jumps to Augment → Seeded Recipes.",
            "effect": "Uses the shared augmentation engine and keeps supported annotations synchronized."
          },
          {
            "name": "YOLO",
            "meaning": "Exports YOLO-compatible labels and metadata.",
            "effect": "Suitable for common detection/segmentation training tools."
          },
          {
            "name": "COCO JSON",
            "meaning": "Exports COCO images/categories/annotations.",
            "effect": "Best lossless standards option for RLE masks."
          },
          {
            "name": "Pascal VOC",
            "meaning": "Exports per-image XML annotations.",
            "effect": "Useful for bounding-box workflows expecting VOC."
          },
          {
            "name": "PNG instance masks",
            "meaning": "Exports per-instance binary masks.",
            "effect": "Useful for pixel-mask training pipelines."
          },
          {
            "name": "Export Clean Dataset",
            "meaning": "Writes images, updated annotations, classes, configuration, manifest and validation report to a new folder.",
            "effect": "The source remains unchanged and each export receives a unique destination."
          }
        ]
      }
    ]
  },
  {
    "id": "shortcuts",
    "category": "Reference",
    "title": "Keyboard shortcuts",
    "summary": "Use shortcuts without stealing keystrokes from text or numeric fields.",
    "sections": [
      {
        "title": "Files and editing",
        "controls": [
          {
            "name": "Ctrl+O / Ctrl+Shift+O / Ctrl+Alt+O",
            "meaning": "Open image, images folder or labelled dataset.",
            "effect": "Mirrors the three explicit input workflows."
          },
          {
            "name": "Ctrl+S / Ctrl+Shift+S / Ctrl+Shift+A",
            "meaning": "Save current, save modified or save all.",
            "effect": "Matches the toolbar scopes."
          },
          {
            "name": "Ctrl++ / Ctrl+- / Ctrl+0",
            "meaning": "Zoom in, zoom out or fit.",
            "effect": "Changes only the view."
          },
          {
            "name": "A / D",
            "meaning": "Previous or next image.",
            "effect": "Reserved globally for browsing."
          }
        ]
      },
      {
        "title": "Panels and annotation",
        "controls": [
          {
            "name": "W",
            "meaning": "Immediately starts or stops whichever annotation type is currently selected.",
            "effect": "No Draw-button initialization is required; it works after using class or mode selectors."
          },
          {
            "name": "B, P, M, K, C",
            "meaning": "Selects and starts box, polygon, mask, pose, or classification creation directly.",
            "effect": "Active only in Annotate."
          },
          {
            "name": "Enter / Esc",
            "meaning": "Finishes polygon/mask/pose or cancels active drawing.",
            "effect": "Context-sensitive to the current annotation action."
          },
          {
            "name": "Shortcuts button",
            "meaning": "Opens the compact categorized shortcut list.",
            "effect": "Use this when you need keys only; use Advanced Tutorial for explanations."
          }
        ]
      }
    ]
  },
  {
    "id": "performance-safety",
    "category": "Reference",
    "title": "Performance, non-destructive behavior and troubleshooting",
    "summary": "Know what is temporary, what is committed and which settings affect only preview speed.",
    "sections": [
      {
        "title": "Performance",
        "controls": [
          {
            "name": "Perf: High",
            "meaning": "Uses available OpenCL acceleration, CPU threads and up to a 1920 px preview.",
            "effect": "Recommended for most systems; full-resolution Apply remains authoritative."
          },
          {
            "name": "Perf: Low",
            "meaning": "Uses a smaller 720 px preview with conservative CPU work.",
            "effect": "Use when interaction is slow or no dedicated GPU is available."
          },
          {
            "name": "About",
            "meaning": "Reports detected CPU, GPU/OpenCL, threads, OpenCV version and active profile.",
            "effect": "Shows real detected capabilities rather than assuming hardware support."
          }
        ]
      },
      {
        "title": "State and safety",
        "controls": [
          {
            "name": "Live preview",
            "meaning": "Temporary visual result from current controls.",
            "effect": "Not added to History until Apply."
          },
          {
            "name": "Committed edit",
            "meaning": "An operation recorded in the global timeline.",
            "effect": "Can be undone, redone or reached by clicking History."
          },
          {
            "name": "Reset / Reset All",
            "meaning": "Returns current or all images to their original in-session state.",
            "effect": "Clears related edit history; use Undo for step-by-step reversal."
          },
          {
            "name": "Dataset export",
            "meaning": "Writes a new output folder.",
            "effect": "Preserves source images, source labels and original dataset structure."
          }
        ]
      }
    ]
  }
];

const CATEGORY_ORDER = [
  "Foundations", "Transform", "Augment", "Resize & Save", "History",
  "Annotate", "Dataset", "Reference",
];

function searchableText(topic) {
  return [
    topic.category, topic.title, topic.summary,
    ...(topic.sections || []).flatMap((section) => [
      section.title, section.body || "",
      ...(section.controls || []).flatMap((control) => [
        control.name, control.meaning, control.effect,
      ]),
    ]),
  ].join(" ").toLowerCase();
}

export function showAdvancedTutorial(initialTopic = "inputs") {
  let activeId = ADVANCED_TOPICS.some((topic) => topic.id === initialTopic)
    ? initialTopic : ADVANCED_TOPICS[0].id;
  let modalApi = null;

  const root = document.createElement("div");
  root.className = "advanced-guide";

  const toolbar = document.createElement("div");
  toolbar.className = "advanced-guide-toolbar";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Search every feature, control or effect…";
  search.setAttribute("aria-label", "Search advanced tutorial topics");
  const count = document.createElement("span");
  toolbar.append(search, count);

  const layout = document.createElement("div");
  layout.className = "advanced-guide-layout";
  const nav = document.createElement("nav");
  nav.className = "advanced-guide-nav";
  nav.setAttribute("aria-label", "Advanced tutorial topics");
  const article = document.createElement("article");
  article.className = "advanced-guide-article";
  layout.append(nav, article);
  root.append(toolbar, layout);

  function matchingTopics() {
    const query = search.value.trim().toLowerCase();
    return query
      ? ADVANCED_TOPICS.filter((topic) => searchableText(topic).includes(query))
      : ADVANCED_TOPICS;
  }

  function renderNav() {
    const matches = matchingTopics();
    const matchIds = new Set(matches.map((topic) => topic.id));
    nav.innerHTML = "";
    count.textContent = search.value.trim()
      ? `${matches.length} matching topic${matches.length === 1 ? "" : "s"}`
      : `${ADVANCED_TOPICS.length} topics · choose any order`;

    for (const category of CATEGORY_ORDER) {
      const topics = ADVANCED_TOPICS.filter(
        (topic) => topic.category === category && matchIds.has(topic.id),
      );
      if (!topics.length) continue;
      const group = document.createElement("section");
      const heading = document.createElement("h3");
      heading.textContent = category;
      group.append(heading);
      for (const topic of topics) {
        const choice = document.createElement("button");
        choice.textContent = topic.title;
        choice.classList.toggle("active", topic.id === activeId);
        choice.setAttribute("aria-current", topic.id === activeId ? "page" : "false");
        choice.addEventListener("click", () => {
          activeId = topic.id;
          renderNav();
          renderTopic(topic);
        });
        group.append(choice);
      }
      nav.append(group);
    }

    if (!matches.length) {
      const empty = document.createElement("p");
      empty.className = "advanced-guide-empty";
      empty.textContent = "No tutorial topic matches that search.";
      nav.append(empty);
      article.innerHTML = "";
      const articleEmpty = document.createElement("p");
      articleEmpty.className = "advanced-guide-empty";
      articleEmpty.textContent = "Try a control name such as Hough, crop, class, seed or mask.";
      article.append(articleEmpty);
    } else if (!matchIds.has(activeId)) {
      activeId = matches[0].id;
      renderTopic(matches[0]);
      renderNav();
    }
  }

  function renderTopic(topic) {
    article.innerHTML = "";
    article.scrollTop = 0;

    const eyebrow = document.createElement("span");
    eyebrow.className = "advanced-guide-eyebrow";
    eyebrow.textContent = topic.category;
    const headingRow = document.createElement("div");
    headingRow.className = "advanced-guide-heading";
    const title = document.createElement("h2");
    title.textContent = topic.title;
    headingRow.append(title);
    if (topic.panel) {
      const open = document.createElement("button");
      open.className = "primary";
      open.textContent = "Open this panel";
      open.addEventListener("click", async () => {
        const mode = {
          transform: "transform",
          augment: "augment",
          annotation: "annotate",
          auto_annotate: "auto_annotate",
          local_ai: "ai_annotate",
        }[topic.panel];
        // Close the reference before a protected mode transition so its
        // Save/Export/Abandon/Cancel dialog is never hidden behind this modal.
        modalApi?.close();
        if (mode && !(await requestWorkingMode(mode))) return;
        setActive(topic.panel);
      });
      headingRow.append(open);
    }
    const summary = document.createElement("p");
    summary.className = "advanced-guide-summary";
    summary.textContent = topic.summary;
    article.append(eyebrow, headingRow, summary);

    const jumpRow = document.createElement("div");
    jumpRow.className = "advanced-guide-jumps";
    for (const [index, section] of (topic.sections || []).entries()) {
      const jump = document.createElement("button");
      jump.textContent = section.title;
      jump.addEventListener("click", () => {
        article.querySelector(`[data-guide-section="${index}"]`)?.scrollIntoView({
          block: "start", behavior: "smooth",
        });
      });
      jumpRow.append(jump);
    }
    article.append(jumpRow);

    for (const [index, section] of (topic.sections || []).entries()) {
      const block = document.createElement("section");
      block.className = "advanced-guide-section";
      block.dataset.guideSection = String(index);
      const sectionTitle = document.createElement("h3");
      sectionTitle.textContent = section.title;
      block.append(sectionTitle);
      if (section.body) {
        const body = document.createElement("p");
        body.textContent = section.body;
        block.append(body);
      }
      if (section.controls?.length) {
        const tableWrap = document.createElement("div");
        tableWrap.className = "advanced-guide-table-wrap";
        const table = document.createElement("table");
        table.className = "advanced-guide-table";
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        for (const label of ["Control or concept", "What it means", "Use and effect"]) {
          const th = document.createElement("th");
          th.textContent = label;
          headerRow.append(th);
        }
        thead.append(headerRow);
        const tbody = document.createElement("tbody");
        for (const control of section.controls) {
          const row = document.createElement("tr");
          for (const value of [control.name, control.meaning, control.effect]) {
            const cell = document.createElement("td");
            cell.textContent = value;
            row.append(cell);
          }
          tbody.append(row);
        }
        table.append(thead, tbody);
        tableWrap.append(table);
        block.append(tableWrap);
      }
      article.append(block);
    }

    const footer = document.createElement("p");
    footer.className = "advanced-guide-footer";
    footer.textContent = "This reference is non-linear. Choose any topic from the left or search for a control by name.";
    article.append(footer);
  }

  search.addEventListener("input", renderNav);
  renderNav();
  renderTopic(ADVANCED_TOPICS.find((topic) => topic.id === activeId));
  modalApi = showModal({
    title: "Advanced Tutorial",
    content: root,
    className: "advanced-tutorial-modal",
  });
  window.setTimeout(() => search.focus(), 0);
  return modalApi;
}
