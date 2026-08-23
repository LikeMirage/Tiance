import { memo, useMemo } from "react";

import { useI18n } from "../../../shared/i18n";
import { useKnowledgeContentFiles } from "../model/useKnowledgeContentFiles";
import "./knowledge-content-dashboard.css";

type KnowledgeContentDashboardProps = {
  projectId: string | null;
  projectName: string;
};

export const KnowledgeContentDashboard = memo(function KnowledgeContentDashboard({
  projectId,
  projectName,
}: KnowledgeContentDashboardProps) {
  const { language, t } = useI18n();
  const { error, items, state, unreadablePaths } = useKnowledgeContentFiles(projectId);
  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(language, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
    [language],
  );

  return (
    <section className="knowledge-content-dashboard" aria-label={t("knowledgeContent.ariaLabel")}>
      <header className="knowledge-content-dashboard__header">
        <div>
          <h2>{projectName}</h2>
          <p>{t("knowledgeContent.fileCount", { count: items.length })}</p>
        </div>
      </header>

      {error ? (
        <p className="knowledge-content-dashboard__notice knowledge-content-dashboard__notice--error">
          {t("knowledgeContent.loadError", { message: error })}
        </p>
      ) : null}
      {unreadablePaths.length > 0 ? (
        <p className="knowledge-content-dashboard__notice">
          {t("knowledgeContent.unreadable", { count: unreadablePaths.length })}
        </p>
      ) : null}

      {state === "loading" ? (
        <div className="knowledge-content-dashboard__empty">{t("knowledgeContent.loading")}</div>
      ) : state === "error" ? null : items.length === 0 ? (
        <div className="knowledge-content-dashboard__empty">{t("knowledgeContent.empty")}</div>
      ) : (
        <div className="knowledge-content-dashboard__table-wrap">
          <table className="knowledge-content-dashboard__table">
            <thead>
              <tr>
                <th>{t("knowledgeContent.file")}</th>
                <th>{t("knowledgeContent.modifiedAt")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.path}>
                  <td>
                    <strong>{item.name}</strong>
                    {item.path !== item.name ? <span>{item.path}</span> : null}
                  </td>
                  <td>
                    <time dateTime={new Date(item.mtime_ms).toISOString()}>
                      {dateFormatter.format(new Date(item.mtime_ms))}
                    </time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
});
