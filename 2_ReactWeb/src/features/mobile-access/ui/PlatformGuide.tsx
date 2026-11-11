import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import type { Platform } from "./PlatformConnectionPanel";
import feishuStart from "../content/feishu/quick-start.md?raw";
import feishuCommands from "../content/feishu/commands.md?raw";
import feishuFaq from "../content/feishu/faq.md?raw";
import wechatStart from "../content/wechat/quick-start.md?raw";
import wechatCommands from "../content/wechat/commands.md?raw";
import wechatFaq from "../content/wechat/faq.md?raw";

const guides = {
  feishu: { quickStart: feishuStart, commands: feishuCommands, faq: feishuFaq },
  wechat: { quickStart: wechatStart, commands: wechatCommands, faq: wechatFaq },
};
export function PlatformGuide({ platform, tab }: { platform: Platform; tab: "quickStart" | "commands" | "faq" }) {
  return <section className="telegram-guide"><LazyMarkdownPreview content={guides[platform][tab]} /></section>;
}
