import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";

import type { Project } from "../../../entities/project/model/project";
import { getTheme, getThemeProjectPreviewUrl } from "../../../services/theme";
import type { ThemeDefinition } from "../../../shared/theme";
import "../../../shared/ui/specialized-collection-overview/specialized-collection-overview.css";
import "./theme-collection-overview.css";

type ThemeCollectionOverviewProps = {
  activeThemeId: string | null;
  isActive: boolean;
  isApplyingTheme: boolean;
  onApplyTheme?: (themeId: string) => void;
  onOpenProject: (projectId: string) => void;
  onSelectProject: (projectId: string) => void;
  projects: Project[];
  selectedProjectId: string | null;
};

type ThemeCollectionCardData = {
  previewUrl: string | null;
  theme: ThemeDefinition;
};

export function ThemeCollectionOverview({
  activeThemeId,
  isActive,
  isApplyingTheme,
  onApplyTheme,
  onOpenProject,
  onSelectProject,
  projects,
  selectedProjectId,
}: ThemeCollectionOverviewProps) {
  const [themeCards, setThemeCards] = useState<ReadonlyMap<string, ThemeCollectionCardData>>(
    () => new Map(),
  );
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const projectKey = projects
    .map((project) => `${project.project_id}:${project.updated_at}`)
    .join("|");

  useEffect(() => {
    if (!isActive) return;
    let disposed = false;
    setState("loading");
    setError(null);
    void Promise.allSettled(
      projects.map(async (project) => {
        const [theme, previewUrl] = await Promise.all([
          getTheme(project.project_id),
          getThemeProjectPreviewUrl(project.project_id).catch(() => null),
        ]);
        return [project.project_id, { previewUrl, theme }] as const;
      }),
    ).then((results) => {
      if (disposed) return;
      const loadedThemeCards = new Map<string, ThemeCollectionCardData>();
      for (const result of results) {
        if (result.status === "fulfilled") {
          loadedThemeCards.set(result.value[0], result.value[1]);
        }
      }
      setThemeCards(loadedThemeCards);
      setState("ready");
    });
    return () => {
      disposed = true;
    };
  }, [isActive, projectKey, projects]);

  const cards = useMemo(
    () => projects.map((project) => {
      return { project, data: themeCards.get(project.project_id) ?? null };
    }),
    [projects, themeCards],
  );

  if (state === "loading") {
    return <div className="specialized-collection-overview__state">正在加载主题总览…</div>;
  }
  if (state === "error") {
    return (
      <div className="specialized-collection-overview__state specialized-collection-overview__state--error">
        {error ?? "主题总览加载失败。"}
      </div>
    );
  }
  if (projects.length === 0) {
    return <div className="specialized-collection-overview__state">当前分类没有主题。</div>;
  }

  return (
    <section className="specialized-collection-overview" aria-label="主题总览">
      <div className="specialized-collection-overview__grid">
        {cards.map(({ data, project }) => {
          const theme = data?.theme ?? null;
          const isSelected = selectedProjectId === project.project_id;
          const isApplied = activeThemeId === theme?.id;
          return (
            <article
              className={
                isSelected
                  ? "specialized-collection-overview__card specialized-collection-overview__card--selected"
                  : "specialized-collection-overview__card"
              }
              key={project.project_id}
              onClick={() => onSelectProject(project.project_id)}
              onDoubleClick={() => onOpenProject(project.project_id)}
            >
              <header className="specialized-collection-overview__header">
                <span className="specialized-collection-overview__identity">
                  <strong title={project.name}>{project.name}</strong>
                  <span>
                    {theme
                      ? theme.mode === "dark" ? "深色主题" : "浅色主题"
                      : "尚未配置"}
                  </span>
                </span>
              </header>
              {theme ? (
                <ThemePreview previewUrl={data?.previewUrl ?? null} theme={theme} />
              ) : (
                <p className="specialized-collection-overview__description">
                  添加有效的 theme.json 后可预览和应用。
                </p>
              )}
              <footer className="specialized-collection-overview__footer">
                <span>{formatUpdatedAt(project.updated_at)}</span>
                <button
                  className={
                    isApplied
                      ? "specialized-collection-overview__apply-switch specialized-collection-overview__apply-switch--on"
                      : "specialized-collection-overview__apply-switch"
                  }
                  type="button"
                  role="switch"
                  aria-checked={isApplied}
                  aria-label={`应用主题 ${project.name}`}
                  title={isApplied ? "当前正在使用" : "应用此主题"}
                  disabled={!theme || isApplyingTheme || !onApplyTheme}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (!isApplied && theme) onApplyTheme?.(theme.id);
                  }}
                >
                  <span>应用</span>
                  <i aria-hidden="true" />
                </button>
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function ThemePreview({
  previewUrl,
  theme,
}: {
  previewUrl: string | null;
  theme: ThemeDefinition;
}) {
  const [failedPreviewUrl, setFailedPreviewUrl] = useState<string | null>(null);
  if (previewUrl && previewUrl !== failedPreviewUrl) {
    return (
      <div className="theme-collection-overview__preview theme-collection-overview__preview--image">
        <img
          alt={`${theme.name} 主题预览`}
          loading="lazy"
          onError={() => setFailedPreviewUrl(previewUrl)}
          src={previewUrl}
        />
      </div>
    );
  }

  const { accent, surface, text } = theme.tokens.color;
  const style = {
    "--theme-preview-accent": accent.base,
    "--theme-preview-canvas": surface.canvas,
    "--theme-preview-panel": surface.panel,
    "--theme-preview-panel-alt": surface.panelAlt,
    "--theme-preview-text": text.primary,
  } as CSSProperties;
  return (
    <div className="theme-collection-overview__preview" style={style} aria-hidden="true">
      <span className="theme-collection-overview__preview-sidebar" />
      <span className="theme-collection-overview__preview-content">
        <i />
        <i />
        <i />
      </span>
      <span className="theme-collection-overview__preview-panel" />
      <span className="theme-collection-overview__swatches">
        <i />
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}

function formatUpdatedAt(value: string) {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "更新时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}
