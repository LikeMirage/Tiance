import capabilitiesEn from "../content/en-US/capabilities.md?raw";
import faqEn from "../content/en-US/faq.md?raw";
import quickStartEn from "../content/en-US/quick-start.md?raw";
import repositorySyncEn from "../content/en-US/repository-sync.md?raw";
import capabilitiesRu from "../content/ru-RU/capabilities.md?raw";
import faqRu from "../content/ru-RU/faq.md?raw";
import quickStartRu from "../content/ru-RU/quick-start.md?raw";
import repositorySyncRu from "../content/ru-RU/repository-sync.md?raw";
import capabilitiesZh from "../content/zh-CN/capabilities.md?raw";
import faqZh from "../content/zh-CN/faq.md?raw";
import quickStartZh from "../content/zh-CN/quick-start.md?raw";
import repositorySyncZh from "../content/zh-CN/repository-sync.md?raw";

export type GithubSettingsTab =
  | "login"
  | "quick-start"
  | "capabilities"
  | "repository-sync"
  | "faq";

export type GithubGuideTab = Exclude<GithubSettingsTab, "login">;

const guideContent = {
  "en-US": {
    capabilities: capabilitiesEn,
    faq: faqEn,
    "quick-start": quickStartEn,
    "repository-sync": repositorySyncEn,
  },
  "ru-RU": {
    capabilities: capabilitiesRu,
    faq: faqRu,
    "quick-start": quickStartRu,
    "repository-sync": repositorySyncRu,
  },
  "zh-CN": {
    capabilities: capabilitiesZh,
    faq: faqZh,
    "quick-start": quickStartZh,
    "repository-sync": repositorySyncZh,
  },
} satisfies Record<string, Record<GithubGuideTab, string>>;

export function getGithubGuideContent(language: string, tab: GithubGuideTab) {
  const locale = language.toLowerCase().startsWith("zh")
    ? "zh-CN"
    : language.toLowerCase().startsWith("ru")
      ? "ru-RU"
      : "en-US";
  return guideContent[locale][tab];
}
