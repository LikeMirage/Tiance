import { useI18n } from "../../../shared/i18n";
import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import { getTelegramGuide } from "../model/telegramGuideContent";

export function TelegramGuide({ tab }: { tab: "quickStart" | "commands" | "faq" }) {
  const { language } = useI18n();
  return <section className="telegram-guide"><LazyMarkdownPreview content={getTelegramGuide(language, tab)} /></section>;
}
