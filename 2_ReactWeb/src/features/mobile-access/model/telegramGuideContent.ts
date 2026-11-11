import quickZh from "../content/zh-CN/quick-start.md?raw";
import commandsZh from "../content/zh-CN/commands.md?raw";
import faqZh from "../content/zh-CN/faq.md?raw";
import quickEn from "../content/en-US/quick-start.md?raw";
import commandsEn from "../content/en-US/commands.md?raw";
import faqEn from "../content/en-US/faq.md?raw";
import quickRu from "../content/ru-RU/quick-start.md?raw";
import commandsRu from "../content/ru-RU/commands.md?raw";
import faqRu from "../content/ru-RU/faq.md?raw";

const content = {
  zh: { quickStart: quickZh, commands: commandsZh, faq: faqZh },
  en: { quickStart: quickEn, commands: commandsEn, faq: faqEn },
  ru: { quickStart: quickRu, commands: commandsRu, faq: faqRu },
};
export function getTelegramGuide(language: string, tab: "quickStart" | "commands" | "faq") {
  const locale = language.toLowerCase().startsWith("zh") ? "zh" : language.toLowerCase().startsWith("ru") ? "ru" : "en";
  return content[locale][tab];
}
