import type JSZip from "jszip";

const chartRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart";
const drawingRelationshipType = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing";
const packageRelationshipMarker = "/_rels/";
const relationshipFileSuffix = ".rels";
const spreadsheetMainNamespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const officeRelationshipNamespace = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

type ExcelPreviewBufferResult = {
  buffer: ArrayBuffer;
  removedUnsupportedDrawingCount: number;
};

type UnsupportedDrawingParts = {
  chartPaths: Set<string>;
  drawingPaths: Set<string>;
};

export async function removeUnsupportedExcelDrawings(buffer: ArrayBuffer): Promise<ExcelPreviewBufferResult> {
  if (!isOpenXmlPackage(buffer)) {
    return { buffer, removedUnsupportedDrawingCount: 0 };
  }

  const { default: JSZip } = await import("jszip");
  const zip = await JSZip.loadAsync(buffer);
  const unsupportedParts = await findChartDrawingParts(zip);

  if (unsupportedParts.drawingPaths.size === 0) {
    return { buffer, removedUnsupportedDrawingCount: 0 };
  }

  let removedUnsupportedDrawingCount = 0;

  for (const relationshipsPath of Object.keys(zip.files)) {
    if (!isWorksheetRelationshipsPath(relationshipsPath)) continue;

    const relationshipsFile = zip.file(relationshipsPath);
    if (!relationshipsFile) continue;

    const relationshipsXml = await relationshipsFile.async("string");
    const removeResult = removeUnsupportedDrawingRelationships(
      relationshipsXml,
      relationshipsPath,
      unsupportedParts.drawingPaths,
    );

    if (removeResult.removedRelationshipIds.size === 0) continue;

    zip.file(relationshipsPath, removeResult.xml);
    removedUnsupportedDrawingCount += removeResult.removedRelationshipIds.size;

    const worksheetPath = sourcePartPathFromRelationshipsPath(relationshipsPath);
    const worksheetFile = zip.file(worksheetPath);
    if (!worksheetFile) continue;

    const worksheetXml = await worksheetFile.async("string");
    zip.file(worksheetPath, removeWorksheetDrawingNodes(worksheetXml, removeResult.removedRelationshipIds));
  }

  await removeUnsupportedDrawingPackageParts(zip, unsupportedParts);

  return {
    buffer: await zip.generateAsync({ type: "arraybuffer" }),
    removedUnsupportedDrawingCount,
  };
}

function isOpenXmlPackage(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer, 0, Math.min(buffer.byteLength, 4));
  return bytes.length >= 2 && bytes[0] === 0x50 && bytes[1] === 0x4b;
}

async function findChartDrawingParts(zip: JSZip): Promise<UnsupportedDrawingParts> {
  const chartPaths = new Set<string>();
  const drawingPaths = new Set<string>();

  for (const relationshipsPath of Object.keys(zip.files)) {
    if (!isDrawingRelationshipsPath(relationshipsPath)) continue;

    const relationshipsFile = zip.file(relationshipsPath);
    if (!relationshipsFile) continue;

    const relationshipsXml = await relationshipsFile.async("string");
    const relationshipsDocument = parseXml(relationshipsXml);
    const relationships = Array.from(relationshipsDocument.getElementsByTagName("Relationship"));
    const chartRelationshipTargets = relationships
      .filter((relationship) => relationship.getAttribute("Type") === chartRelationshipType)
      .map((relationship) => relationship.getAttribute("Target"))
      .filter((target): target is string => Boolean(target));

    if (chartRelationshipTargets.length > 0) {
      drawingPaths.add(sourcePartPathFromRelationshipsPath(relationshipsPath));
      for (const target of chartRelationshipTargets) {
        chartPaths.add(resolveRelationshipTarget(relationshipsPath, target));
      }
    }
  }

  return { chartPaths, drawingPaths };
}

function removeUnsupportedDrawingRelationships(
  xml: string,
  relationshipsPath: string,
  unsupportedDrawings: Set<string>,
) {
  const document = parseXml(xml);
  const removedRelationshipIds = new Set<string>();

  for (const relationship of Array.from(document.getElementsByTagName("Relationship"))) {
    if (relationship.getAttribute("Type") !== drawingRelationshipType) continue;

    const target = relationship.getAttribute("Target");
    const id = relationship.getAttribute("Id");
    if (!target || !id) continue;

    const drawingPath = resolveRelationshipTarget(relationshipsPath, target);
    if (!unsupportedDrawings.has(drawingPath)) continue;

    relationship.parentNode?.removeChild(relationship);
    removedRelationshipIds.add(id);
  }

  return {
    removedRelationshipIds,
    xml: serializeXml(document),
  };
}

function removeWorksheetDrawingNodes(xml: string, removedRelationshipIds: Set<string>) {
  const document = parseXml(xml);
  const drawingNodes = [
    ...Array.from(document.getElementsByTagNameNS(spreadsheetMainNamespace, "drawing")),
    ...Array.from(document.getElementsByTagName("drawing")),
  ];

  for (const drawingNode of drawingNodes) {
    const relationshipId = drawingNode.getAttributeNS(officeRelationshipNamespace, "id")
      ?? drawingNode.getAttribute("r:id");

    if (relationshipId && removedRelationshipIds.has(relationshipId)) {
      drawingNode.parentNode?.removeChild(drawingNode);
    }
  }

  return serializeXml(document);
}

async function removeUnsupportedDrawingPackageParts(zip: JSZip, unsupportedParts: UnsupportedDrawingParts) {
  const removedPartNames = new Set<string>();

  for (const drawingPath of unsupportedParts.drawingPaths) {
    zip.remove(drawingPath);
    zip.remove(relationshipsPathFromSourcePartPath(drawingPath));
    removedPartNames.add(`/${drawingPath}`);
  }

  for (const chartPath of unsupportedParts.chartPaths) {
    zip.remove(chartPath);
    zip.remove(relationshipsPathFromSourcePartPath(chartPath));
    removedPartNames.add(`/${chartPath}`);
  }

  await removeContentTypeOverrides(zip, removedPartNames);
}

async function removeContentTypeOverrides(zip: JSZip, removedPartNames: Set<string>) {
  const contentTypesFile = zip.file("[Content_Types].xml");
  if (!contentTypesFile) return;

  const xml = await contentTypesFile.async("string");
  const document = parseXml(xml);
  for (const override of Array.from(document.getElementsByTagName("Override"))) {
    const partName = override.getAttribute("PartName");
    if (partName && removedPartNames.has(partName)) {
      override.parentNode?.removeChild(override);
    }
  }
  zip.file("[Content_Types].xml", serializeXml(document));
}

function isDrawingRelationshipsPath(path: string) {
  return /^xl\/drawings\/_rels\/[^/]+\.xml\.rels$/.test(path);
}

function isWorksheetRelationshipsPath(path: string) {
  return /^xl\/worksheets\/_rels\/sheet\d+\.xml\.rels$/.test(path);
}

function resolveRelationshipTarget(relationshipsPath: string, target: string) {
  if (target.startsWith("/")) {
    return normalizePackagePath(target.slice(1));
  }

  const sourcePath = sourcePartPathFromRelationshipsPath(relationshipsPath);
  const sourceDirectory = sourcePath.slice(0, sourcePath.lastIndexOf("/"));
  return normalizePackagePath(`${sourceDirectory}/${target}`);
}

function sourcePartPathFromRelationshipsPath(relationshipsPath: string) {
  const markerIndex = relationshipsPath.lastIndexOf(packageRelationshipMarker);
  if (markerIndex < 0 || !relationshipsPath.endsWith(relationshipFileSuffix)) {
    return relationshipsPath;
  }

  const directory = relationshipsPath.slice(0, markerIndex);
  const fileName = relationshipsPath.slice(
    markerIndex + packageRelationshipMarker.length,
    -relationshipFileSuffix.length,
  );

  return `${directory}/${fileName}`;
}

function normalizePackagePath(path: string) {
  const stack: string[] = [];

  for (const part of path.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      stack.pop();
      continue;
    }
    stack.push(part);
  }

  return stack.join("/");
}

function relationshipsPathFromSourcePartPath(sourcePartPath: string) {
  const lastSlashIndex = sourcePartPath.lastIndexOf("/");
  if (lastSlashIndex < 0) {
    return `_rels/${sourcePartPath}.rels`;
  }

  const directory = sourcePartPath.slice(0, lastSlashIndex);
  const fileName = sourcePartPath.slice(lastSlashIndex + 1);
  return `${directory}/_rels/${fileName}.rels`;
}

function parseXml(xml: string) {
  const document = new DOMParser().parseFromString(xml, "application/xml");
  if (document.getElementsByTagName("parsererror").length > 0) {
    throw new Error("Excel 文件内部 XML 解析失败。");
  }
  return document;
}

function serializeXml(document: XMLDocument) {
  return new XMLSerializer().serializeToString(document);
}
