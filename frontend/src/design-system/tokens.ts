export const spacing = { 2: 2, 4: 4, 6: 6, 8: 8, 10: 10, 12: 12, 16: 16, 20: 20, 24: 24, 28: 28, 32: 32, 36: 36, 40: 40, 48: 48, 64: 64, 72: 72, 80: 80 } as const;

export const radius = { sm: 4, md: 8, lg: 12, xl: 16, full: 1000 } as const;

export type SpacingToken = keyof typeof spacing;
export type RadiusToken = keyof typeof radius;
