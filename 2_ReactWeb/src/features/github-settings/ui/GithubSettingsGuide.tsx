import { LazyMarkdownPreview } from "../../markdown-preview/ui/LazyMarkdownPreview";
import {
  getGithubGuideContent,
  type GithubGuideTab,
} from "../model/githubGuideContent";

type GithubSettingsGuideProps = {
  language: string;
  tab: GithubGuideTab;
};

export function GithubSettingsGuide({ language, tab }: GithubSettingsGuideProps) {
  return (
    <section className="github-settings__guide">
      <LazyMarkdownPreview content={getGithubGuideContent(language, tab)} />
    </section>
  );
}
