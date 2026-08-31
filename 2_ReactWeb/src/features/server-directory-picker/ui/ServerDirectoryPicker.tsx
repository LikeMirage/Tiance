import {
  ArrowRight,
  ArrowUp,
  Folder,
  HardDrive,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { createPortal } from "react-dom";

import {
  listServerDirectories,
  type ServerDirectoryListing,
} from "../../../services/workspace/serverDirectoryBrowser";
import { useI18n } from "../../../shared/i18n";
import "./server-directory-picker.css";

type ServerDirectoryPickerProps = {
  onCancel: () => void;
  onSelect: (path: string) => Promise<void>;
};

export function ServerDirectoryPicker({ onCancel, onSelect }: ServerDirectoryPickerProps) {
  const { t } = useI18n();
  const [listing, setListing] = useState<ServerDirectoryListing | null>(null);
  const [pathInput, setPathInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const requestRef = useRef<AbortController | null>(null);

  const loadDirectory = useCallback(async (path?: string) => {
    requestRef.current?.abort();
    const request = new AbortController();
    requestRef.current = request;
    setIsLoading(true);
    setError(null);
    try {
      const nextListing = await listServerDirectories(path, request.signal);
      if (request.signal.aborted || requestRef.current !== request) return;
      setListing(nextListing);
      setPathInput(nextListing.path);
    } catch (loadError) {
      if (request.signal.aborted) return;
      setError(loadError instanceof Error ? loadError.message : t("workspace.directoryPicker.loadFailed"));
    } finally {
      if (requestRef.current === request) {
        setIsLoading(false);
      }
    }
  }, [t]);

  useEffect(() => {
    void loadDirectory();
    return () => requestRef.current?.abort();
  }, [loadDirectory]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isSubmitting) onCancel();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isSubmitting, onCancel]);

  const handlePathSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (pathInput.trim()) void loadDirectory(pathInput);
  };

  const handleSelect = async () => {
    if (!listing || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await onSelect(listing.path);
    } catch (selectError) {
      setError(selectError instanceof Error ? selectError.message : t("workspace.directoryPicker.importFailed"));
      setIsSubmitting(false);
    }
  };

  return createPortal(
    <div className="server-directory-picker__backdrop" role="presentation">
      <section
        className="server-directory-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="server-directory-picker-title"
      >
        <header className="server-directory-picker__header">
          <h3 id="server-directory-picker-title">{t("workspace.directoryPicker.title")}</h3>
          <button
            type="button"
            aria-label={t("common.actions.close")}
            disabled={isSubmitting}
            onClick={onCancel}
          >
            <X size={17} />
          </button>
        </header>

        <form className="server-directory-picker__path" onSubmit={handlePathSubmit}>
          <input
            aria-label={t("workspace.directoryPicker.pathLabel")}
            value={pathInput}
            disabled={isSubmitting}
            placeholder={t("workspace.directoryPicker.pathPlaceholder")}
            onChange={(event) => setPathInput(event.target.value)}
          />
          <button
            type="submit"
            aria-label={t("workspace.directoryPicker.go")}
            title={t("workspace.directoryPicker.go")}
            disabled={isLoading || isSubmitting || !pathInput.trim()}
          >
            <ArrowRight size={16} weight="bold" />
          </button>
        </form>

        <div className="server-directory-picker__body">
          <nav className="server-directory-picker__roots" aria-label={t("workspace.directoryPicker.roots")}>
            {listing?.roots.map((root) => (
              <button
                type="button"
                key={root.path}
                title={root.path}
                disabled={isSubmitting}
                onClick={() => void loadDirectory(root.path)}
              >
                <HardDrive size={16} />
                <span>{root.name}</span>
              </button>
            ))}
          </nav>

          <div className="server-directory-picker__directory-pane">
            {listing?.parent_path ? (
              <button
                className="server-directory-picker__directory server-directory-picker__parent"
                type="button"
                disabled={isLoading || isSubmitting}
                onClick={() => void loadDirectory(listing.parent_path ?? undefined)}
              >
                <ArrowUp size={16} />
                <span>{t("workspace.directoryPicker.parent")}</span>
              </button>
            ) : null}
            <div className="server-directory-picker__directories">
              {!isLoading && listing?.directories.length === 0 ? (
                <p className="server-directory-picker__empty">{t("workspace.directoryPicker.empty")}</p>
              ) : null}
              {listing?.directories.map((directory) => (
                <button
                  className="server-directory-picker__directory"
                  type="button"
                  key={directory.path}
                  title={directory.path}
                  disabled={isLoading || isSubmitting}
                  onClick={() => void loadDirectory(directory.path)}
                >
                  <Folder size={16} weight="fill" />
                  <span>{directory.name}</span>
                </button>
              ))}
              {isLoading ? (
                <p className="server-directory-picker__empty">{t("common.status.loading")}</p>
              ) : null}
            </div>
          </div>
        </div>

        <footer className="server-directory-picker__footer">
          <div className="server-directory-picker__selection">
            <span>{t("workspace.directoryPicker.selected")}</span>
            <strong title={listing?.path}>{listing?.path ?? "—"}</strong>
          </div>
          {error ? <p role="alert">{error}</p> : null}
          <div className="server-directory-picker__actions">
            <button type="button" disabled={isSubmitting} onClick={onCancel}>
              {t("common.actions.cancel")}
            </button>
            <button
              className="server-directory-picker__primary"
              type="button"
              disabled={!listing || isLoading || isSubmitting}
              onClick={() => void handleSelect()}
            >
              {isSubmitting
                ? t("workspace.directoryPicker.importing")
                : t("workspace.directoryPicker.import")}
            </button>
          </div>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
