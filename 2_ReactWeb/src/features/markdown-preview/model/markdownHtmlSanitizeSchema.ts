import { defaultSchema } from "rehype-sanitize";

// Shared by the synchronous preview and the background conversation renderer.
export const markdownHtmlSanitizeSchema = {
  ...defaultSchema,
  protocols: {
    ...defaultSchema.protocols,
    href: [...(defaultSchema.protocols?.href ?? []), "tiance-local-path"],
  },
  tagNames: [...(defaultSchema.tagNames ?? []), "center", "details", "summary", "label"],
  attributes: {
    ...defaultSchema.attributes,
    "*": [...(defaultSchema.attributes?.["*"] ?? []), "align", "className", "style", "title"],
    a: [...(defaultSchema.attributes?.a ?? []), "href", "title", "target", "rel"],
    img: [...(defaultSchema.attributes?.img ?? []), "src", "alt", "title", "width", "height"],
    td: [...(defaultSchema.attributes?.td ?? []), "align", "colSpan", "rowSpan"],
    th: [...(defaultSchema.attributes?.th ?? []), "align", "colSpan", "rowSpan"],
  },
};
