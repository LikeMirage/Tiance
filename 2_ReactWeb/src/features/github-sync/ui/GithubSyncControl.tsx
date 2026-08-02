import {
  ArrowDown,
  ArrowUp,
  GitBranch,
  GithubLogo,
  LinkBreak,
  X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { GithubSyncCollection } from "../../../services/github/githubSyncApi";
import { useI18n } from "../../../shared/i18n";
import { useWorkspaceNavigation } from "../../../shared/model/workspaceNavigation";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import { useGithubSync } from "../model/useGithubSync";
import "./github-sync-control.css";

export function GithubSyncControl({
  collection,
  disabled,
}: {
  collection: GithubSyncCollection;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const { openGithubSettings } = useWorkspaceNavigation();
  const [open, setOpen] = useState(false);
  const sync = useGithubSync(collection, open);
  const [editing, setEditing] = useState(false);
  const [repository, setRepository] = useState("");
  const [branch, setBranch] = useState("main");
  const [remotePath, setRemotePath] = useState("");
  const [commitMessage, setCommitMessage] = useState("");

  const repositoryOptions = useMemo(
    () => (sync.overview?.repositories ?? []).map((item) => ({
      label: `${item.fullName}${item.canPush ? "" : ` · ${t("githubSync.readOnly")}`}`,
      value: item.fullName,
    })),
    [sync.overview?.repositories, t],
  );
  const selectedRepository = sync.overview?.repositories.find(
    (item) => item.fullName === repository,
  );
  const boundRepository = sync.overview?.repositories.find(
    (item) => `https://github.com/${item.fullName}` === sync.overview?.binding?.repository,
  );

  useEffect(() => {
    const binding = sync.overview?.binding;
    if (!binding) {
      if (!repository && sync.overview?.repositories[0]) {
        const first = sync.overview.repositories[0];
        setRepository(first.fullName);
        setBranch(first.defaultBranch);
      }
      return;
    }
    if (!editing) {
      setRepository(binding.repository.replace("https://github.com/", ""));
      setBranch(binding.branch);
      setRemotePath(binding.remotePath);
    }
  }, [editing, repository, sync.overview]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !sync.loading) setOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, sync.loading]);

  const binding = sync.overview?.binding;
  const showBindingForm = !binding || editing;

  return (
    <>
      <button
        className="github-sync-control__trigger"
        disabled={disabled}
        onClick={() => setOpen(true)}
        title={t("githubSync.title")}
        type="button"
      >
        <GitBranch size={15} />
        <span>{t("githubSync.trigger")}</span>
        {binding ? <i aria-label={t("githubSync.bound")} /> : null}
      </button>

      {open ? createPortal(
        <div
          className="github-sync-control__backdrop"
          onMouseDown={() => { if (!sync.loading) setOpen(false); }}
          role="presentation"
        >
          <section
            aria-label={t("githubSync.title")}
            aria-busy={sync.loading}
            aria-modal="true"
            className="github-sync-control__dialog"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <header>
              <div>
                <GithubLogo size={20} />
                <div>
                  <h3>{t("githubSync.title")}</h3>
                  <p>{t(`githubSync.collections.${collection}`)}</p>
                </div>
              </div>
              <button
                aria-label={t("common.actions.close")}
                disabled={sync.loading}
                onClick={() => setOpen(false)}
                type="button"
              ><X size={17} /></button>
            </header>

            <div className="github-sync-control__body">
              {!sync.overview && sync.loading ? (
                <div className="github-sync-control__state">{t("githubSync.loading")}</div>
              ) : !sync.overview?.connected ? (
                <div className="github-sync-control__state">
                  <p>{t("githubSync.loginRequired")}</p>
                  <button onClick={() => { setOpen(false); openGithubSettings(); }} type="button">
                    {t("githubSync.openSettings")}
                  </button>
                </div>
              ) : showBindingForm ? (
                <div className="github-sync-control__form">
                  <label>
                    <span>{t("githubSync.repository")}</span>
                    <OptionSelect
                      disabled={sync.loading || repositoryOptions.length === 0}
                      floating
                      onChange={(value) => {
                        setRepository(value);
                        const item = sync.overview?.repositories.find((candidate) => candidate.fullName === value);
                        if (item) setBranch(item.defaultBranch);
                      }}
                      options={repositoryOptions}
                      placeholder={t("githubSync.selectRepository")}
                      showSelectedOption
                      value={repository}
                    />
                  </label>
                  {repositoryOptions.length === 0 ? (
                    <p className="github-sync-control__hint">{t("githubSync.noRepositories")}</p>
                  ) : null}
                  <label>
                    <span>{t("githubSync.branch")}</span>
                    <input disabled={sync.loading} onChange={(event) => setBranch(event.target.value)} value={branch} />
                  </label>
                  <label>
                    <span>{t("githubSync.remotePath")}</span>
                    <input
                      disabled={sync.loading}
                      onChange={(event) => setRemotePath(event.target.value)}
                      placeholder={t("githubSync.remotePathPlaceholder")}
                      value={remotePath}
                    />
                  </label>
                  {selectedRepository && !selectedRepository.canPush ? (
                    <p className="github-sync-control__warning">{t("githubSync.readOnlyWarning")}</p>
                  ) : null}
                  <div className="github-sync-control__actions">
                    {binding ? (
                      <button disabled={sync.loading} onClick={() => setEditing(false)} type="button">
                        {t("common.actions.cancel")}
                      </button>
                    ) : null}
                    <button
                      className="is-primary"
                      disabled={sync.loading || !repository.trim() || !branch.trim()}
                      onClick={() => void sync.bind(repository, branch, remotePath).then((saved) => {
                        if (saved) setEditing(false);
                      })}
                      type="button"
                    >{t("githubSync.saveBinding")}</button>
                  </div>
                </div>
              ) : sync.plan ? (
                <PlanView
                  commitMessage={commitMessage}
                  loading={sync.loading}
                  onBack={sync.clearPlan}
                  onCommitMessageChange={setCommitMessage}
                  onConfirm={() => void sync.apply(sync.plan?.direction === "push" ? commitMessage : null)}
                  plan={sync.plan}
                />
              ) : (
                <div className="github-sync-control__bound">
                  <div className="github-sync-control__binding">
                    <strong>{binding.repository.replace("https://github.com/", "")}</strong>
                    <span>{binding.branch}{binding.remotePath ? ` / ${binding.remotePath}` : ""}</span>
                  </div>
                  <p>{t("githubSync.planFirst")}</p>
                  <div className="github-sync-control__sync-actions">
                    <button disabled={sync.loading} onClick={() => void sync.preview("pull")} type="button">
                      <ArrowDown size={16} />{t("githubSync.previewPull")}
                    </button>
                    <button
                      disabled={sync.loading || boundRepository?.canPush === false}
                      onClick={() => void sync.preview("push")}
                      type="button"
                    >
                      <ArrowUp size={16} />{t("githubSync.previewPush")}
                    </button>
                  </div>
                  {boundRepository?.canPush === false ? (
                    <p className="github-sync-control__warning">{t("githubSync.readOnlyWarning")}</p>
                  ) : null}
                  <div className="github-sync-control__management">
                    <button disabled={sync.loading} onClick={() => setEditing(true)} type="button">
                      {t("githubSync.changeBinding")}
                    </button>
                    <button disabled={sync.loading} onClick={() => void sync.unbind()} type="button">
                      <LinkBreak size={14} />{t("githubSync.unbind")}
                    </button>
                  </div>
                </div>
              )}

              {sync.error ? <div className="github-sync-control__error" role="alert">{sync.error}</div> : null}
              {sync.loading && sync.overview ? (
                <div className="github-sync-control__progress" role="status">
                  {t("githubSync.working")}
                </div>
              ) : null}
              {sync.result ? (
                <div className="github-sync-control__result" role="status">
                  {t(`githubSync.results.${sync.result}`)}
                </div>
              ) : null}
            </div>
          </section>
        </div>,
        document.body,
      ) : null}
    </>
  );
}

function PlanView({
  commitMessage,
  loading,
  onBack,
  onCommitMessageChange,
  onConfirm,
  plan,
}: {
  commitMessage: string;
  loading: boolean;
  onBack: () => void;
  onCommitMessageChange: (value: string) => void;
  onConfirm: () => void;
  plan: NonNullable<ReturnType<typeof useGithubSync>["plan"]>;
}) {
  const { t } = useI18n();
  return (
    <div className="github-sync-control__plan">
      <div className="github-sync-control__summary">
        <strong>{t(plan.direction === "push" ? "githubSync.pushPlan" : "githubSync.pullPlan")}</strong>
        <span>+{plan.additions}</span><span>~{plan.updates}</span><span>-{plan.deletions}</span>
      </div>
      {plan.changes.length === 0 ? (
        <div className="github-sync-control__state">{t("githubSync.noChanges")}</div>
      ) : (
        <div className="github-sync-control__changes">
          {plan.changes.map((change) => (
            <div key={change.path}>
              <b data-kind={change.kind}>{change.kind === "add" ? "+" : change.kind === "delete" ? "−" : "~"}</b>
              <span title={change.path}>{change.path}</span>
              <small>{formatBytes(change.size)}</small>
            </div>
          ))}
        </div>
      )}
      {plan.direction === "push" && plan.changes.length > 0 ? (
        <label>
          <span>{t("githubSync.commitMessage")}</span>
          <input
            disabled={loading}
            maxLength={200}
            onChange={(event) => onCommitMessageChange(event.target.value)}
            placeholder={t("githubSync.commitMessagePlaceholder")}
            value={commitMessage}
          />
        </label>
      ) : null}
      <div className="github-sync-control__actions">
        <button disabled={loading} onClick={onBack} type="button">{t("githubSync.back")}</button>
        {plan.changes.length > 0 ? (
          <button className="is-primary" disabled={loading} onClick={onConfirm} type="button">
            {t(plan.direction === "push" ? "githubSync.confirmPush" : "githubSync.confirmPull")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
