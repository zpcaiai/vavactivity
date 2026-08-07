export const iconSymbols = { success: "✓", warning: "!", danger: "×", info: "i", close: "×", menu: "☰", search: "⌕" } as const;
export type VavIconName = keyof typeof iconSymbols;
