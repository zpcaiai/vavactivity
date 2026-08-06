# Design Token Model

`packages/design-tokens/design-token-manifest.yaml` is the source inventory. Primitive values feed semantic light, dark and high-contrast themes; semantic values feed components. Layout, motion and density are separate namespaces. The generated CSS, JSON, TypeScript and SCSS files are deterministic build products.

Application code consumes semantic or component variables, never primitive color literals. `scripts/ui/control.py token-check` rejects hard-coded hex/RGB values in governed UI. Existing application CSS is recorded as dated debt and cannot be used to exempt new shared code.

Token releases begin as drafts, require a reviewer different from the author, and cannot be released until build, component, accessibility and visual evidence are individually accepted and checksum-bound.
