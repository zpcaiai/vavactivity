export const requiredViewports = [{ code: "mobile-360", width: 360, height: 800 }, { code: "tablet-768", width: 768, height: 1024 }, { code: "desktop-1440", width: 1440, height: 1000 }, { code: "wide-1920", width: 1920, height: 1080 }] as const;
export const requiredThemes = ["light", "dark", "high-contrast"] as const;
export const requiredLocales = ["zh-CN", "zh-TW", "en"] as const;
export function horizontalOverflow(documentWidth: number, viewportWidth: number) { return Math.max(0, documentWidth - viewportWidth); }
export function visualCaseId(input: { page: string; viewport: string; theme: string; locale: string; density: string }) { return [input.page, input.viewport, input.theme, input.locale, input.density].map((value) => value.toLowerCase().replace(/[^a-z0-9-]+/gu, "-")).join("__"); }
export function assertSyntheticFixture(value: unknown) { const text = JSON.stringify(value); if (/@(?:gmail|qq|163)\.com|1[3-9]\d{9}|BEGIN PRIVATE KEY/iu.test(text)) throw new Error("visual fixture may contain real or sensitive data"); return value; }
