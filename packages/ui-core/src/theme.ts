export type VavTheme = "light" | "dark" | "high-contrast";
export type VavDensity = "comfortable" | "compact";

export function applyUiPreferences(
  target: HTMLElement,
  theme: VavTheme,
  density: VavDensity
) {
  target.dataset.vavTheme = theme;
  target.dataset.vavDensity = density;
}
