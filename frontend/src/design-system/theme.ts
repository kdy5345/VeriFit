export const lightTheme = {
  background: { root: { regular: "#FFFFFF", strong: "#F2F3F7" }, fill: { static: "#FFFFFF", staticTranslucent: "#FFFFFFCC", regular: "#9298AD14", strong: "#9298AD1F", inverted: "#111214", interactive: "#FFFFFFCC" }, state: { hover: "#1D213314", pressed: "#1D21331F", focused: "#9298AD1F" } },
  content: { base: "#1D2133", additive: "#1D2133CC", assistive: "#1D213399", disabled: "#1D213366", inverted: "#EBEDF2", elevated: "#FFFFFF" },
  border: { divider: { regular: "#9298AD33", strong: "#1D2133" }, outline: { regular: "#9298AD29", strong: "#1D2133" } },
  semantic: { brand: { strong: "#3567F3", regular: "#3567F314" }, success: { strong: "#16B874", regular: "#16B87414" }, warning: { strong: "#FFBF0F", regular: "#FFBF0F14" }, danger: { strong: "#FF244B", regular: "#FF244B14" } },
} as const;

export const darkTheme = {
  background: { root: { regular: "#101012", strong: "#0B0C0D" }, fill: { static: "#101012", staticTranslucent: "#101012CC", regular: "#EBEDF205", strong: "#EBEDF20A", inverted: "#EBEDF2", interactive: "#EBEDF20A" }, state: { hover: "#EBEDF214", pressed: "#EBEDF229", focused: "#EBEDF21F" } },
  content: { base: "#EBEDF2", additive: "#EBEDF2CC", assistive: "#EBEDF299", disabled: "#EBEDF266", inverted: "#1D2133", elevated: "#FFFFFF" },
  border: { divider: { regular: "#EBEDF214", strong: "#EBEDF2" }, outline: { regular: "#EBEDF20A", strong: "#EBEDF2" } },
  semantic: { brand: { strong: "#3567F3", regular: "#3567F31F" }, success: { strong: "#16B874", regular: "#16B8741F" }, warning: { strong: "#FFBF0F", regular: "#FFBF0F1F" }, danger: { strong: "#FF244B", regular: "#FF244B1F" } },
} as const;

export const elevatedTheme = { ...darkTheme, content: { ...darkTheme.content, assistive: "#EBEDF2CC", disabled: "#EBEDF2CC" } } as const;
export const themes = { light: lightTheme, dark: darkTheme, elevated: elevatedTheme } as const;
export type ThemeName = keyof typeof themes;

export function setTheme(theme: ThemeName) { document.documentElement.dataset.theme = theme; }
