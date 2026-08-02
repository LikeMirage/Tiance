import enUSLocale from "./builtin/en-US.json";
import ruRULocale from "./builtin/ru-RU.json";
import zhCNLocale from "./builtin/zh-CN.json";

export type LocaleDirection = "ltr" | "rtl";

export type LocalePackage<TMessages> = {
  schemaVersion: number;
  locale: string;
  displayName: string;
  direction: LocaleDirection;
  messages: TMessages;
};

type ImportedLocalePackage<TMessages> = Omit<LocalePackage<TMessages>, "direction"> & {
  direction: string;
};

type DictionaryShape<T> = T extends string
  ? string
  : {
      readonly [K in keyof T]: DictionaryShape<T[K]>;
    };

export const zhCN = zhCNLocale.messages;
export const enUS = enUSLocale.messages satisfies DictionaryShape<typeof zhCN>;
export const ruRU = ruRULocale.messages satisfies DictionaryShape<typeof zhCN>;

function toLocalePackage<TMessages>(locale: ImportedLocalePackage<TMessages>): LocalePackage<TMessages> {
  if (locale.direction !== "ltr" && locale.direction !== "rtl") {
    throw new Error(`Unsupported locale direction: ${locale.direction}`);
  }

  return locale as LocalePackage<TMessages>;
}

export const builtinLocalePackages = {
  "zh-CN": toLocalePackage(zhCNLocale),
  "en-US": toLocalePackage(enUSLocale),
  "ru-RU": toLocalePackage(ruRULocale),
} as const satisfies Record<string, LocalePackage<typeof zhCN>>;

export const dictionaries = {
  "zh-CN": zhCN,
  "en-US": enUS,
  "ru-RU": ruRU,
} as const;

export type SupportedLanguage = keyof typeof dictionaries;
export type TranslationDictionary = typeof zhCN;

export function isSupportedLanguage(value: string): value is SupportedLanguage {
  return Object.prototype.hasOwnProperty.call(dictionaries, value);
}

type LeafPath<T> = T extends string
  ? never
  : {
      [K in Extract<keyof T, string>]: T[K] extends string ? K : `${K}.${LeafPath<T[K]>}`;
    }[Extract<keyof T, string>];

export type TranslationKey = LeafPath<TranslationDictionary>;
