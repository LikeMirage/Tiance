import {
  ChatsCircle,
  FilePlus,
  FolderOpen,
  Plus,
} from "@phosphor-icons/react";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { EmbeddedPanel } from "../../../shared/ui/embedded-panel/EmbeddedPanel";
import type { EditorExternalPathReferenceRequest } from "../../../entities/editor/model/editorReference";
import type { ProjectKind } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import { OptionSelect } from "../../../shared/ui/option-select/OptionSelect";
import { buildComposerProjectReference, referenceComposerProject } from "../model/composerProjectReference";
import { ChatComposerCategoryLayout } from "./ChatComposerCategoryLayout";
import type { ChatProjectReferenceCatalog } from "./ChatComposerTypes";

type AddCategory = "file" | "conversation" | "project";

type ChatComposerAddMenuProps = {
  isOpen: boolean;
  panelContainer: HTMLElement | null;
  onOpenChange: (isOpen: boolean) => void;
  onSelectFiles: () => Promise<void>;
  projectId: string | null;
  projectCatalog?: ChatProjectReferenceCatalog;
  onReferenceExternalPath?: (reference: EditorExternalPathReferenceRequest) => void;
};

const CATEGORIES: Array<{
  icon: typeof FilePlus;
  id: AddCategory;
  label: string;
}> = [
  { id: "file", label: "文件", icon: FilePlus },
  { id: "conversation", label: "会话", icon: ChatsCircle },
  { id: "project", label: "项目", icon: FolderOpen },
];

const PROJECT_COLLECTIONS = [
  { value: "project", labelKey: "sidebar.sections.overview" },
  { value: "tool", labelKey: "sidebar.sections.tools" },
  { value: "knowledge", labelKey: "sidebar.sections.knowledge" },
  { value: "experience", labelKey: "sidebar.sections.experience" },
  { value: "role", labelKey: "sidebar.sections.roles" },
  { value: "provider", labelKey: "sidebar.sections.models" },
  { value: "theme", labelKey: "sidebar.sections.themes" },
] as const;

export function ChatComposerAddMenu({
  isOpen,
  panelContainer,
  onOpenChange,
  onSelectFiles,
  projectId,
  projectCatalog,
  onReferenceExternalPath,
}: ChatComposerAddMenuProps) {
  const { t } = useI18n();
  const generatedId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const [activeCategory, setActiveCategory] = useState<AddCategory>("file");
  const [selectedCollection, setSelectedCollection] = useState<ProjectKind | null>(null);
  const [selectedProjectCategoryId, setSelectedProjectCategoryId] = useState<string | null>(null);
  const currentProject = projectCatalog?.projects.find((project) => project.project_id === projectId);
  const collection = selectedCollection ?? currentProject?.project_kind ?? "project";
  const collectionOptions = useMemo(() => PROJECT_COLLECTIONS.map(({ value, labelKey }) => ({
    value, label: t(labelKey),
  })), [t]);
  const categoryOptions = useMemo(
    () => projectCatalog?.categories
      .filter((category) => category.category_kind === collection)
      .map((category) => ({ label: category.name, value: category.category_id })) ?? [],
    [collection, projectCatalog?.categories],
  );
  const categoryId = categoryOptions.find((option) => option.value === selectedProjectCategoryId)?.value
    ?? categoryOptions.find((option) => option.value === currentProject?.category_id)?.value
    ?? categoryOptions[0]?.value
    ?? "";
  const categoryProjects = useMemo(() => projectCatalog?.projects.filter(
    (project) => project.project_kind === collection && project.category_id === categoryId,
  ) ?? [], [collection, categoryId, projectCatalog?.projects]);

  useEffect(() => {
    if (isOpen) setActiveCategory("file");
  }, [isOpen]);

  const panelId = `${generatedId}-panel`;
  const panel = isOpen ? (
        <EmbeddedPanel container={panelContainer} id={panelId}
          className={activeCategory === "project" ? "chat-composer-add-menu embedded-panel--split-header" : "chat-composer-add-menu"}
          ariaLabel="添加到对话"
          title={activeCategory === "project" ? "添加项目" : "添加到对话"}
          onClose={() => onOpenChange(false)} headerContent={
            activeCategory === "project" ? (
              <>
                <OptionSelect
                  className="chat-composer-add-menu__project-collection"
                  ariaLabel="选择集"
                  options={collectionOptions}
                  value={collection}
                  onChange={(kind) => {
                    setSelectedCollection(kind);
                    setSelectedProjectCategoryId(null);
                  }}
                  showSelectedOption
                  variant="underline-overlay"
                />
                <OptionSelect
                  className="chat-composer-add-menu__project-category"
                  ariaLabel="项目分类"
                  placeholder="项目分类"
                  options={categoryOptions}
                  value={categoryId}
                  onChange={setSelectedProjectCategoryId}
                  disabled={categoryOptions.length === 0}
                  showSelectedOption
                  variant="underline-overlay"
                />
              </>
            ) : null
          }>
          <ChatComposerCategoryLayout label="内容类型" categories={CATEGORIES}
            activeCategory={activeCategory} onSelect={setActiveCategory}>
              {activeCategory === "file" ? (
                <button
                  className="chat-composer-add-menu__option"
                  type="button"
                  onClick={() => {
                    onOpenChange(false);
                    void onSelectFiles();
                  }}
                >
                  <FilePlus size={18} weight="regular" aria-hidden="true" />
                  <span className="chat-composer-add-menu__option-copy">
                    <strong>从资源管理器中选择文件</strong>
                    <span>选择一个或多个本机文件，添加到当前输入内容</span>
                  </span>
                  <span className="chat-composer-add-menu__badge">多选</span>
                </button>
              ) : null}
              {activeCategory === "project" ? (
                categoryProjects.length > 0 ? categoryProjects.map((project) => (
                  <button
                    key={project.project_id}
                    className="chat-composer-add-menu__option chat-composer-add-menu__project"
                    type="button"
                    title={project.root_path}
                    disabled={!onReferenceExternalPath || !buildComposerProjectReference(project)}
                    onClick={() => {
                      if (!referenceComposerProject(project, onReferenceExternalPath)) return;
                      onOpenChange(false);
                    }}
                  >
                    <FolderOpen size={17} weight="regular" aria-hidden="true" />
                    <span className="chat-composer-add-menu__option-copy">
                      <strong>{project.name}</strong>
                      <span>{project.root_path}</span>
                    </span>
                  </button>
                )) : (
                  <div className="chat-composer-add-menu__empty" role="status">
                    {projectCatalog?.isLoading ? "正在加载项目…"
                      : projectCatalog?.error ? "项目列表加载失败"
                        : categoryId ? "此分类暂无项目" : "此集暂无分类"}
                  </div>
                )
              ) : null}
              {activeCategory === "conversation" ? (
                <button className="chat-composer-add-menu__option" type="button" disabled>
                  <ChatsCircle size={18} weight="regular" aria-hidden="true" />
                  <span className="chat-composer-add-menu__option-copy">
                    <strong>添加会话</strong>
                    <span>引用另一会话中的内容与上下文</span>
                  </span>
                  <span className="chat-composer-add-menu__badge">暂未开放</span>
                </button>
              ) : null}
          </ChatComposerCategoryLayout>
        </EmbeddedPanel>
      )
    : null;

  return (
    <>
      {panel}
      <button
        ref={triggerRef}
        className={[
          "ai-panel__composer-add",
          isOpen ? "ai-panel__composer-add--open" : "",
        ].filter(Boolean).join(" ")}
        type="button"
        aria-controls={isOpen ? panelId : undefined}
        aria-expanded={isOpen}
        aria-label="添加到对话"
        title="添加到对话"
        onClick={() => onOpenChange(!isOpen)}
      >
        <Plus aria-hidden="true" size={17} weight="regular" />
      </button>
    </>
  );
}
