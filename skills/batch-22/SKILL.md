---
name: vav-batch-22-design-system
description: Implement or review VAV tokens, shared components, layouts, accessibility, responsive behavior, Storybook, visual regression and UI release governance.
---

# Goal

Operate one governed interface language for user and administrator applications while keeping automated evidence distinct from human accessibility and visual approval.

# Required workflow

1. Read the design documents, token manifest and the relevant Batch 22 child Skill.
2. Use semantic tokens and shared components; do not add product-specific literals to governed packages.
3. Run component, Storybook, axe, responsive, visual and page audits with synthetic data.
4. Register checksum-bound evidence and enforce independent approval for audits, baselines and releases.
5. Run `make ui-verify` and inspect `build/ui/evidence-manifest.json`.

# Evidence boundary

Keep production `NOT_CERTIFIED` until assistive-technology, real-device and visual baseline reviews are independently accepted.
