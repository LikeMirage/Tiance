export type DesktopWindowSizePreferences = {
  height: number;
  maximized: boolean;
  width: number;
};

export type DesktopWindowSizePreferenceUpdate = Partial<DesktopWindowSizePreferences>;

export const DESKTOP_WINDOW_SIZE_DEFAULTS: DesktopWindowSizePreferences = {
  height: 900,
  maximized: false,
  width: 1440,
};

export const DESKTOP_WINDOW_SIZE_LIMITS = {
  height: {
    max: 4320,
    min: 720,
  },
  width: {
    max: 7680,
    min: 1080,
  },
} as const;

export function normalizeDesktopWindowSizePreferences(
  preferences: DesktopWindowSizePreferenceUpdate | null | undefined,
): DesktopWindowSizePreferences {
  return {
    height: normalizeDesktopWindowSizeValue(
      preferences?.height,
      DESKTOP_WINDOW_SIZE_DEFAULTS.height,
      DESKTOP_WINDOW_SIZE_LIMITS.height.min,
      DESKTOP_WINDOW_SIZE_LIMITS.height.max,
    ),
    maximized: typeof preferences?.maximized === "boolean"
      ? preferences.maximized
      : DESKTOP_WINDOW_SIZE_DEFAULTS.maximized,
    width: normalizeDesktopWindowSizeValue(
      preferences?.width,
      DESKTOP_WINDOW_SIZE_DEFAULTS.width,
      DESKTOP_WINDOW_SIZE_LIMITS.width.min,
      DESKTOP_WINDOW_SIZE_LIMITS.width.max,
    ),
  };
}

export function normalizeDesktopWindowSizePreferenceUpdate(
  update: DesktopWindowSizePreferenceUpdate,
): DesktopWindowSizePreferenceUpdate {
  const normalized: DesktopWindowSizePreferenceUpdate = {};
  if (update.height !== undefined) {
    normalized.height = normalizeDesktopWindowSizeValue(
      update.height,
      DESKTOP_WINDOW_SIZE_DEFAULTS.height,
      DESKTOP_WINDOW_SIZE_LIMITS.height.min,
      DESKTOP_WINDOW_SIZE_LIMITS.height.max,
    );
  }
  if (update.maximized !== undefined) {
    normalized.maximized = update.maximized;
  }
  if (update.width !== undefined) {
    normalized.width = normalizeDesktopWindowSizeValue(
      update.width,
      DESKTOP_WINDOW_SIZE_DEFAULTS.width,
      DESKTOP_WINDOW_SIZE_LIMITS.width.min,
      DESKTOP_WINDOW_SIZE_LIMITS.width.max,
    );
  }
  return normalized;
}

export function fitDesktopWindowSizeToCurrentScreen(
  preferences: DesktopWindowSizePreferences,
): DesktopWindowSizePreferences {
  const availableWidth = Math.floor(window.screen.availWidth || preferences.width);
  const availableHeight = Math.floor(window.screen.availHeight || preferences.height);
  return {
    ...preferences,
    height: normalizeDesktopWindowSizeValue(
      preferences.height,
      DESKTOP_WINDOW_SIZE_DEFAULTS.height,
      DESKTOP_WINDOW_SIZE_LIMITS.height.min,
      Math.max(DESKTOP_WINDOW_SIZE_LIMITS.height.min, availableHeight),
    ),
    width: normalizeDesktopWindowSizeValue(
      preferences.width,
      DESKTOP_WINDOW_SIZE_DEFAULTS.width,
      DESKTOP_WINDOW_SIZE_LIMITS.width.min,
      Math.max(DESKTOP_WINDOW_SIZE_LIMITS.width.min, availableWidth),
    ),
  };
}

function normalizeDesktopWindowSizeValue(
  value: number | null | undefined,
  fallback: number,
  min: number,
  max: number,
) {
  const candidate = Number.isFinite(value) ? Number(value) : fallback;
  return Math.min(Math.max(Math.round(candidate), min), max);
}
