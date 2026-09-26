export const fontFamily = { ko: '"SUIT Variable", sans-serif', en: '"Inter Variable", sans-serif' } as const;
export const fontWeight = { weak: 400, regular: 500, strong: { ko: 700, en: 600 } } as const;

export const typography = {
  display: { fontSize: 48, lineHeight: 70 }, title: { fontSize: 24, lineHeight: 34 },
  headline: { fontSize: 20, lineHeight: 28 }, subhead: { fontSize: 18, lineHeight: 26 },
  body: { fontSize: 16, lineHeight: 24 }, callout: { fontSize: 14, lineHeight: 20 },
  footnote: { fontSize: 12, lineHeight: 18 }, caption: { fontSize: 10, lineHeight: 14 },
  paragraphLarge: { fontSize: 16, lineHeight: 28.8 }, paragraphSmall: { fontSize: 14, lineHeight: 24 },
} as const;

export const typographyScale = {
  100: typography,
  135: { title: [32.4, 45.9], headline: [27, 37.8], body: [21.6, 32.4] },
  150: { title: [36, 51], headline: [30, 42], body: [24, 36] },
  200: { title: [48, 68], headline: [40, 56], body: [32, 48] },
} as const;

export type TypographyScale = keyof typeof typographyScale;
