"""Deterministic, reusable augmentation recipes for dataset variants."""

from __future__ import annotations

from typing import Any

import numpy as np

BUILTIN_RECIPES: dict[str, dict[str, Any]] = {
    "balanced": {
        "name": "Balanced robustness",
        "description": "Small geometry, exposure and noise changes for general training.",
        "ranges": {
            "rotation": [-6, 6],
            "scale": [92, 108],
            "translate": [-8, 8],
            "exposure": [-0.35, 0.35],
            "noise": [0, 10],
            "flip_horizontal_probability": 50,
        },
    },
    "low_light": {
        "name": "Low-light resilience",
        "description": "Darker exposure with mild blur and sensor noise.",
        "ranges": {
            "exposure": [-1.2, -0.25],
            "gaussian_blur": [0, 18],
            "noise": [4, 20],
        },
    },
    "geometry": {
        "name": "Geometry robustness",
        "description": "Rotation, translation, scaling, shear and optional horizontal flip.",
        "ranges": {
            "rotation": [-12, 12],
            "scale": [85, 115],
            "translate": [-16, 16],
            "shear": [-5, 5],
            "flip_horizontal_probability": 50,
        },
    },
    "clarity": {
        "name": "Blur and clarity variation",
        "description": "Alternates blur, softness, sharpening and exposure.",
        "ranges": {
            "gaussian_blur": [0, 30],
            "softness": [0, 18],
            "sharpen": [0, 35],
            "exposure": [-0.25, 0.4],
        },
    },
}

RECIPE_FIELDS: list[dict[str, Any]] = [
    {"id": "white_balance", "name": "White balance", "min": -100, "max": 100, "step": 1},
    {"id": "hsv_hue", "name": "Hue", "min": -180, "max": 180, "step": 1},
    {"id": "hsv_saturation", "name": "Saturation", "min": -100, "max": 100, "step": 1},
    {"id": "hsv_value", "name": "Brightness", "min": -100, "max": 100, "step": 1},
    {"id": "exposure", "name": "Exposure", "min": -2, "max": 2, "step": 0.05},
    {"id": "gaussian_blur", "name": "Blur", "min": 0, "max": 100, "step": 1},
    {"id": "softness", "name": "Softness", "min": 0, "max": 100, "step": 1},
    {"id": "sharpen", "name": "Sharpen", "min": 0, "max": 100, "step": 1},
    {"id": "oil", "name": "Oil paint", "min": 0, "max": 100, "step": 1},
    {"id": "noise", "name": "Noise", "min": 0, "max": 100, "step": 1},
    {"id": "salt_pepper", "name": "Salt & pepper", "min": 0, "max": 100, "step": 1},
    {"id": "rotation", "name": "Rotation °", "min": -180, "max": 180, "step": 1},
    {"id": "translate", "name": "Shift px", "min": -100, "max": 100, "step": 1},
    {"id": "scale", "name": "Scale %", "min": 50, "max": 150, "step": 1},
    {"id": "shear", "name": "Shear °", "min": -45, "max": 45, "step": 1},
    {
        "id": "flip_horizontal_probability",
        "name": "Horizontal flip chance",
        "min": 0,
        "max": 100,
        "step": 1,
        "probability": True,
    },
    {
        "id": "flip_vertical_probability",
        "name": "Vertical flip chance",
        "min": 0,
        "max": 100,
        "step": 1,
        "probability": True,
    },
]


def recipe_catalog() -> list[dict[str, Any]]:
    return [{"id": recipe_id, **recipe} for recipe_id, recipe in BUILTIN_RECIPES.items()]


def sample_recipe(recipe_id: str, seed: int, item_index: int, copy_index: int) -> dict[str, Any]:
    if recipe_id not in BUILTIN_RECIPES:
        raise ValueError(f"Unknown augmentation recipe: {recipe_id}")
    return sample_custom_recipe(
        BUILTIN_RECIPES[recipe_id]["ranges"], seed, item_index, copy_index
    )


def sample_custom_recipe(
    ranges: dict[str, Any], seed: int, item_index: int, copy_index: int
) -> dict[str, Any]:
    """Sample user-editable ranges deterministically after strict validation."""
    sequence = np.random.SeedSequence([int(seed), int(item_index), int(copy_index)])
    rng = np.random.default_rng(sequence)
    fields = {str(row["id"]): row for row in RECIPE_FIELDS}
    params: dict[str, Any] = {}
    for key, value in ranges.items():
        if key not in fields:
            raise ValueError(f"Unsupported augmentation setting: {key}")
        spec = fields[key]
        if key.endswith("_probability"):
            probability = float(value) / 100
            if not 0 <= probability <= 1:
                raise ValueError(f"{spec['name']} must be between 0 and 100%")
            target = key.removesuffix("_probability")
            params[target] = bool(rng.random() < probability)
        elif isinstance(value, list) and len(value) == 2:
            low, high = float(value[0]), float(value[1])
            if low > high:
                raise ValueError(f"{spec['name']} minimum cannot exceed its maximum")
            if low < float(spec["min"]) or high > float(spec["max"]):
                raise ValueError(
                    f"{spec['name']} must stay between {spec['min']} and {spec['max']}"
                )
            if float(spec["step"]).is_integer():
                params[key] = int(rng.integers(int(low), int(high) + 1))
            else:
                params[key] = float(rng.uniform(low, high))
        else:
            raise ValueError(f"Invalid range for {spec['name']}")
    return params
