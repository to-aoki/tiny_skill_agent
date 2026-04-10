---
name: compare-two-images
description: Compare exactly two input images and describe their differences in text. Use this skill when the user asks to compare two images, detect visual differences, explain what changed between a before/after pair, or summarize mismatches between two screenshots, photos, mockups, or diagrams.
---
# Compare Two Images

Use this skill when the two target images exist in the workspace.
Find them with `list_directory` if needed, then load them with `read_file`.
After a workspace image is read, it is added to `input_images` for later model turns.
Treat loaded images as the primary source of truth.
Do not invent differences that are not visually supported.

## Do This

1. Confirm which two workspace images should be compared.
2. Read both images from the workspace if they are not already present in `input_images`.
3. Confirm that `input_images` contains exactly two images before answering.
4. Compare the two images directly.
5. Describe only meaningful visual differences.
6. Mention if there are no clear differences.
7. Keep the response text-only unless the user asked for a specific format.

## Compare In This Order

1. Overall layout or composition
2. Added, removed, or moved elements
3. Text changes that are clearly readable
4. Color, size, alignment, spacing, or styling changes
5. Any notable content mismatch or anomaly

## Output Rules

- Refer to the images as `image 1` and `image 2` unless the user gives names.
- Be specific and concrete.
- Prefer short bullet points when many differences exist.
- If a region is ambiguous or unreadable, say so.
- If the images appear to show different crops or scales, mention that before comparing details.

## Do Not Do This

- Do not answer before both target images have been read.
- Do not request extra tool actions after the two images are already loaded.
- Do not claim pixel-perfect certainty.
- Do not describe similarities unless they help explain a difference.
- Do not output JSON unless the user asked for it.
