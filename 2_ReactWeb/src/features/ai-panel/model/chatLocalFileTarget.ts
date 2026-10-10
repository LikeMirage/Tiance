import {
  encodeLocalPathLink,
  resolveLocalFileReference,
  type LocalFileReference,
  type LocalFileReferenceContext,
} from "../../../entities/local-file/model/localFileReference";
import {
  getProjectContentFiles,
  type ProjectContentFileSnapshot,
} from "../../../services/project/getProjectContentFiles";

type ResolvedReference = Extract<LocalFileReference, { lookup: "path" }>;

/** Resolve auto-linked filenames against current project content, on click.
 * No root preference, fuzzy match, cached tree, or substitution for explicit
 * paths. Incomplete scans and duplicate names must be reported to the user.
 */
export async function resolveChatLocalFileTarget(
  reference: LocalFileReference,
  context: LocalFileReferenceContext,
  loadSnapshot: (projectId: string, init?: Pick<RequestInit, "signal">) => Promise<ProjectContentFileSnapshot> = getProjectContentFiles,
  signal?: AbortSignal,
): Promise<ResolvedReference> {
  signal?.throwIfAborted();
  if (reference.lookup === "path") return reference;
  if (!context.projectId) throw new Error("当前没有可用于查找文件的项目。");
  const snapshot = await loadSnapshot(context.projectId, { signal });
  signal?.throwIfAborted();
  if (snapshot.unreadable_paths.length > 0) {
    throw new Error(`部分项目路径无法读取，不能确定文件名是否唯一，请使用完整路径：\n${snapshot.unreadable_paths.join("\n")}`);
  }
  const matches = snapshot.items.filter((item) => item.name.toLowerCase() === reference.name.toLowerCase());
  if (matches.length === 0) {
    throw new Error(`项目内容中找不到文件“${reference.name}”。请检查文件名，或使用完整路径。`);
  }
  if (matches.length > 1) {
    throw new Error(`找到多个同名文件“${reference.name}”，请从文件树打开所需文件，或使用完整路径：\n${matches.map((item) => item.path).join("\n")}`);
  }
  const resolved = resolveLocalFileReference(encodeLocalPathLink(`./${matches[0].path}`), context);
  if (!resolved || resolved.lookup !== "path" || resolved.scope !== "workspace") {
    throw new Error("匹配的文件路径不属于当前工作区。");
  }
  return { ...resolved, line: reference.line, rawPath: reference.rawPath };
}
