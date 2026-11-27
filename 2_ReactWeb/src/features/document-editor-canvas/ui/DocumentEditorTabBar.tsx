import type { ReactNode, RefObject } from "react";
import { useState } from "react";
import { ChatsCircle, GlobeSimple, Notebook, Plus, SquaresFour, UserCircleGear, X } from "@phosphor-icons/react";
import { isProjectMemoryDashboardTab } from "../../document-tabs/model/documentTabUtils";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import {
  isFixedDocumentTab,
  isProjectConversationOverviewTab,
  isProjectRoleConfigurationTab,
  isToolDashboardTab,
} from "../model/documentTabClassification";

type DocumentEditorTabIndicator = {
  left: number;
  width: number;
} | null;

type DocumentEditorTabBarProps = {
  overviewTabs?: ReactNode;
  onNewWebTab?: () => void;
  activeTabId: string | null;
  onCancelAutoScroll: () => void;
  onOpenContextMenu: (tabId: string, x: number, y: number) => void;
  onRequestClose: (tabId: string) => void;
  onSelectTab: (tabId: string) => void;
  tabBarRef: RefObject<HTMLDivElement | null>;
  tabIndicator: DocumentEditorTabIndicator;
  tabs: DocumentTab[];
};

export function DocumentEditorTabBar({
  overviewTabs,
  onNewWebTab,
  activeTabId,
  onCancelAutoScroll,
  onOpenContextMenu,
  onRequestClose,
  onSelectTab,
  tabBarRef,
  tabIndicator,
  tabs,
}: DocumentEditorTabBarProps) {
  if (tabs.length === 0 && !onNewWebTab && !overviewTabs) {
    return null;
  }

  return (
    <div className="doc-editor__tabbar">
      <div
        className="doc-editor__tab-scroll"
        ref={tabBarRef}
        onWheel={(event) => {
          const bar = tabBarRef.current;
          if (!bar) return;
          onCancelAutoScroll();
          bar.scrollLeft += Math.abs(event.deltaX) > Math.abs(event.deltaY)
            ? event.deltaX
            : event.deltaY;
        }}
      >
        {overviewTabs}
        {tabIndicator ? (
          <div
            className="doc-editor__tab-indicator"
            style={{
              transform: `translateX(${tabIndicator.left}px)`,
              width: `${tabIndicator.width}px`,
            }}
          />
        ) : null}
        {tabs.map((tab) => (
          <div
            className={buildTabClassName(tab, activeTabId)}
            key={tab.id}
            title={tab.isMissing ? `${tab.displayPath}（找不到文件）` : tab.displayPath}
            onClick={() => onSelectTab(tab.id)}
            onContextMenu={(event) => {
              event.preventDefault();
              if (isFixedDocumentTab(tab)) return;
              onOpenContextMenu(tab.id, event.clientX, event.clientY);
            }}
          >
            {isToolDashboardTab(tab) ? (
              <SquaresFour
                className="doc-editor__tab-icon doc-editor__tab-icon--tool-dashboard"
                size={13}
                weight="fill"
              />
            ) : null}
            {isProjectConversationOverviewTab(tab) ? (
              <ChatsCircle
                className="doc-editor__tab-icon"
                size={13}
                weight="fill"
              />
            ) : null}
            {isProjectRoleConfigurationTab(tab) ? (
              <UserCircleGear
                className="doc-editor__tab-icon doc-editor__tab-icon--role-dashboard"
                size={15}
                weight="fill"
              />
            ) : null}
            {isProjectMemoryDashboardTab(tab) && <Notebook className="doc-editor__tab-icon" size={14} aria-hidden="true" />}
            {tab.kind === "web" && (!tab.displayPath
              ? <span aria-hidden="true" className="doc-editor__home-icon" />
              : <WebTabIcon icon={tab.favicon} />)}
            <DocumentTabTitle tab={tab} />
            {tab.isDirty && <span>●</span>}
            {isFixedDocumentTab(tab) ? null : (
              <button
                className="doc-editor__tab-close"
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  onRequestClose(tab.id);
                }}
              >
                <X size={11} weight="bold" />
              </button>
            )}
          </div>
        ))}
      </div>
      {onNewWebTab && <button className="doc-editor__new-web" type="button" title="新建网页标签" aria-label="新建网页标签" onClick={onNewWebTab}><Plus size={15} /></button>}
    </div>
  );
}

function WebTabIcon({ icon }: { icon?: string }) {
  const [failed, setFailed] = useState<string>();
  return icon && icon !== failed
    ? <img className="doc-editor__tab-icon" src={icon} width={14} height={14} alt="" draggable={false} onError={() => setFailed(icon)} />
    : <GlobeSimple className="doc-editor__tab-icon" size={14} />;
}

function DocumentTabTitle({ tab }: { tab: DocumentTab }) {
  const { title } = tab;
  const dot = tab.filePath || tab.projectFilePath ? title.lastIndexOf(".") : -1;
  if (dot > 0 && dot < title.length - 1) {
    return (
      <span className="doc-editor__tab-title doc-editor__tab-title--file">
        <span className="doc-editor__tab-stem">{title.slice(0, dot)}</span>
        <span className="doc-editor__tab-extension">{title.slice(dot)}</span>
      </span>
    );
  }
  return <span className="doc-editor__tab-title" title={tab.kind === "web" ? title : undefined}>{title}</span>;
}

function buildTabClassName(tab: DocumentTab, activeTabId: string | null) {
  return [
    "doc-editor__tab",
    tab.id === activeTabId ? "doc-editor__tab--active" : "",
    tab.isMissing ? "doc-editor__tab--missing" : "",
  ].filter(Boolean).join(" ");
}
