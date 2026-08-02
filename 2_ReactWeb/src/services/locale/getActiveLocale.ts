import type {
  LocaleDirection,
  TranslationDictionary,
} from "../../shared/i18n";
import { fetchJson } from "../http/httpClient";

export type LocaleDefinition = {
  schemaVersion: 1;
  locale: string;
  displayName: string;
  direction: LocaleDirection;
  messages: TranslationDictionary;
};

export function getActiveLocale(preferredLocale: string): Promise<LocaleDefinition> {
  const query = new URLSearchParams({ preferredLocale });
  return fetchJson<LocaleDefinition>(`/api/locales/active?${query.toString()}`);
}
