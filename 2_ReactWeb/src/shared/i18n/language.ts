import type { SupportedLanguage } from "./locales";

export const DEFAULT_LANGUAGE: SupportedLanguage = "en-US";
const LOCALE_TAG_PATTERN = /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/;

export function resolveSystemLanguage(languages: readonly string[] = readNavigatorLanguages()) {
  const primaryLanguage = languages.find((language) => language.trim().length > 0);
  return primaryLanguage ? normalizeLanguageTag(primaryLanguage) : DEFAULT_LANGUAGE;
}

export function normalizeLanguageTag(language: string): string {
  const normalized = language.trim().replace(/_/g, "-").toLowerCase();
  if (!normalized) {
    return DEFAULT_LANGUAGE;
  }

  if (normalized === "zh" || normalized.startsWith("zh-")) {
    return "zh-CN";
  }

  if (normalized === "ru" || normalized.startsWith("ru-")) {
    return "ru-RU";
  }

  if (normalized === "en" || normalized.startsWith("en-")) {
    return "en-US";
  }

  const canonical = toCanonicalLanguageTag(normalized);
  return LOCALE_TAG_PATTERN.test(canonical) ? canonical : DEFAULT_LANGUAGE;
}

function readNavigatorLanguages() {
  if (typeof navigator === "undefined") {
    return [];
  }

  if (navigator.languages.length > 0) {
    return navigator.languages;
  }

  return navigator.language ? [navigator.language] : [];
}

function toCanonicalLanguageTag(language: string) {
  const [languageCode, ...regionParts] = language.split("-");
  if (regionParts.length === 0) {
    return languageCode;
  }

  return [languageCode, ...regionParts.map(toCanonicalLanguageTagPart)].join("-");
}

function toCanonicalLanguageTagPart(part: string) {
  if (part.length === 2 || /^\d{3}$/.test(part)) {
    return part.toUpperCase();
  }

  if (part.length === 4) {
    return `${part.slice(0, 1).toUpperCase()}${part.slice(1).toLowerCase()}`;
  }

  return part;
}
