import {
  CaretDown,
  CaretRight,
  Database,
  File as PhosphorFile,
  FileAudio,
  FileC,
  FileCode,
  FileCpp,
  FileCSharp,
  FileCss,
  FileCsv,
  FileDoc,
  FileHtml,
  FileImage,
  FileIni,
  FileJs,
  FileJsx,
  FileMd,
  FilePdf,
  FilePpt,
  FilePy,
  FileRs,
  FileSql,
  FileText,
  FileTs,
  FileTsx,
  FileVideo,
  FileVue,
  FileXls,
  FileZip,
  Folder,
  FolderOpen,
  TerminalWindow,
  type Icon,
} from "@phosphor-icons/react";

type FileIconAppearance = {
  Icon?: Icon;
  label?: string;
  kind: string;
};

const FILE_ICON_GROUPS: (FileIconAppearance & { extensions: string[] })[] = [
  { extensions: ["doc", "docx", "docm", "dot", "dotx", "dotm", "odt", "rtf"], Icon: FileDoc, kind: "word" },
  { extensions: ["xls", "xlsx", "xlsm", "xlsb", "xlt", "xltx", "xltm", "ods"], Icon: FileXls, kind: "spreadsheet" },
  { extensions: ["csv", "tsv"], Icon: FileCsv, kind: "spreadsheet" },
  { extensions: ["ppt", "pptx", "pptm", "pps", "ppsx", "ppsm", "pot", "potx", "potm", "odp"], Icon: FilePpt, kind: "presentation" },
  { extensions: ["pdf"], Icon: FilePdf, kind: "pdf" },
  { extensions: ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "ico", "tif", "tiff", "avif", "heic", "heif"], Icon: FileImage, kind: "image" },
  { extensions: ["mp4", "m4v", "mov", "avi", "mkv", "webm", "wmv", "flv", "mpeg", "mpg", "3gp"], Icon: FileVideo, kind: "video" },
  { extensions: ["mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus", "aiff"], Icon: FileAudio, kind: "audio" },
  { extensions: ["txt", "log", "text"], Icon: FileText, kind: "text" },
  { extensions: ["md", "markdown", "mdown", "mdx"], Icon: FileMd, kind: "markdown" },
  { extensions: ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "zst"], Icon: FileZip, kind: "archive" },
  { extensions: ["db", "sqlite", "sqlite3", "db3"], Icon: Database, kind: "database" },
  { extensions: ["py", "pyw", "pyi"], Icon: FilePy, kind: "python" },
  { extensions: ["js", "mjs", "cjs"], Icon: FileJs, kind: "javascript" },
  { extensions: ["ts", "mts", "cts"], Icon: FileTs, kind: "typescript" },
  { extensions: ["jsx"], Icon: FileJsx, kind: "react" },
  { extensions: ["tsx"], Icon: FileTsx, kind: "react" },
  { extensions: ["html", "htm"], Icon: FileHtml, kind: "html" },
  { extensions: ["css"], Icon: FileCss, kind: "css" },
  { extensions: ["scss", "sass"], label: "SASS", kind: "sass" },
  { extensions: ["less"], label: "LESS", kind: "css" },
  { extensions: ["vue"], Icon: FileVue, kind: "vue" },
  { extensions: ["svelte"], label: "SV", kind: "svelte" },
  { extensions: ["c", "h"], Icon: FileC, kind: "c" },
  { extensions: ["cpp", "cc", "cxx", "hpp", "hh", "hxx"], Icon: FileCpp, kind: "cpp" },
  { extensions: ["cs", "csx"], Icon: FileCSharp, kind: "csharp" },
  { extensions: ["java"], label: "JAVA", kind: "java" },
  { extensions: ["go"], label: "GO", kind: "go" },
  { extensions: ["rs"], Icon: FileRs, kind: "rust" },
  { extensions: ["rb", "rake", "gemspec"], label: "RB", kind: "ruby" },
  { extensions: ["php", "phtml"], label: "PHP", kind: "php" },
  { extensions: ["swift"], label: "SW", kind: "swift" },
  { extensions: ["kt", "kts"], label: "KT", kind: "kotlin" },
  { extensions: ["dart"], label: "DART", kind: "dart" },
  { extensions: ["r", "rmd"], label: "R", kind: "r" },
  { extensions: ["lua"], label: "LUA", kind: "lua" },
  { extensions: ["sql"], Icon: FileSql, kind: "sql" },
  { extensions: ["sh", "bash", "zsh", "fish"], Icon: TerminalWindow, kind: "shell" },
  { extensions: ["ps1", "psm1", "psd1"], label: "PS", kind: "powershell" },
  { extensions: ["bat", "cmd"], label: "CMD", kind: "shell" },
  { extensions: ["json", "jsonc", "jsonl"], label: "{}", kind: "json" },
  { extensions: ["yaml", "yml"], label: "YML", kind: "yaml" },
  { extensions: ["toml", "ini", "cfg", "conf", "env"], Icon: FileIni, kind: "config" },
  { extensions: ["tex", "sty", "cls"], label: "TEX", kind: "tex" },
  { extensions: ["xml", "xsl", "xsd", "graphql", "gql"], Icon: FileCode, kind: "code" },
];

const FILE_ICONS_BY_EXTENSION = new Map<string, FileIconAppearance>(
  FILE_ICON_GROUPS.flatMap(({ extensions, ...appearance }) =>
    extensions.map((extension) => [extension, appearance] as const),
  ),
);

export function ChevronRightIcon() {
  return <CaretRight size={12} weight="bold" aria-hidden="true" />;
}

export function ChevronDownIcon() {
  return <CaretDown size={12} weight="bold" aria-hidden="true" />;
}

export function FolderIcon() {
  return <Folder size={14} weight="duotone" aria-hidden="true" />;
}

export function FolderOpenIcon() {
  return <FolderOpen size={14} weight="duotone" aria-hidden="true" />;
}

export function FileIcon({ fileName }: { fileName: string }) {
  const dotIndex = fileName.lastIndexOf(".");
  const extension = dotIndex > 0 ? fileName.slice(dotIndex + 1).toLowerCase() : "";
  const appearance = FILE_ICONS_BY_EXTENSION.get(extension);
  const className = appearance ? `fwt-file-icon fwt-file-icon--${appearance.kind}` : "fwt-file-icon";
  if (appearance?.label) {
    return <FileLanguageBadgeIcon label={appearance.label} className={className} />;
  }
  const FileTypeIcon = appearance?.Icon ?? PhosphorFile;

  return (
    <FileTypeIcon
      size={16}
      weight="duotone"
      className={className}
      aria-hidden="true"
    />
  );
}

// Match the existing Phosphor file outline for languages without a bundled icon.
function FileLanguageBadgeIcon({ label, className }: { label: string; className: string }) {
  return (
    <svg width={16} height={16} viewBox="0 0 256 256" className={className} aria-hidden="true">
      <path d="M208,88H152V32Z" fill="currentColor" opacity={0.2} />
      <path
        d="M48,112V40a8,8,0,0,1,8-8h96l56,56V216a8,8,0,0,1-8,8H176M152,32V88h56"
        fill="none"
        stroke="currentColor"
        strokeWidth={16}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <text
        x={24}
        y={212}
        fill="currentColor"
        fontFamily="Arial, sans-serif"
        fontSize={label.length > 3 ? 56 : 64}
        fontWeight={700}
      >
        {label}
      </text>
    </svg>
  );
}
