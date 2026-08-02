import type { RefObject } from "react";
import { ChatsCircle, SquaresFour, UserCircleGear, X } from "@phosphor-icons/react";

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
  activeTabId,
  onCancelAutoScroll,
  onOpenContextMenu,
  onRequestClose,
  onSelectTab,
  tabBarRef,
  tabIndicator,
  tabs,
}: DocumentEditorTabBarProps) {
  if (tabs.length === 0) {
    return null;
  }

  return (
    <div
      className="doc-editor__tabbar"
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
          title={tab.isMissing ? `${tab.displayPath}（文件已删除）` : tab.displayPath}
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
          <span className="doc-editor__tab-title">{tab.title}{tab.isDirty ? " ●" : ""}</span>
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
  );
}

function buildTabClassName(tab: DocumentTab, activeTabId: string | null) {
  return [
    "doc-editor__tab",
    tab.id === activeTabId ? "doc-editor__tab--active" : "",
    isToolDashboardTab(tab) ? "doc-editor__tab--tool-dashboard" : "",
    isProjectRoleConfigurationTab(tab) ? "doc-editor__tab--role-dashboard" : "",
    tab.isMissing ? "doc-editor__tab--missing" : "",
  ].filter(Boolean).join(" ");
}
