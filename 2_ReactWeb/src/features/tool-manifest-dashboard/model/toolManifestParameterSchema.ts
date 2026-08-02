import { asString, asStringArray, type JsonSchemaProperty } from "./toolManifest";
import type { JsonObject } from "./toolManifestEditorTypes";

export type ParameterOption = {
  description: string;
  value: string;
};

export function ensureObject(target: JsonObject, key: string): JsonObject {
  const current = target[key];
  if (current && typeof current === "object" && !Array.isArray(current)) {
    return current as JsonObject;
  }
  const next: JsonObject = {};
  target[key] = next;
  return next;
}

export function updateInputParameterSchema(
  draft: JsonObject,
  name: string,
  updater: (schema: JsonObject) => void,
) {
  const inputSchema = ensureInputSchema(draft);
  const properties = getInputProperties(inputSchema);
  const schema = toJsonObject(properties[name]);
  updater(schema);
  properties[name] = schema;
  inputSchema.properties = properties;
}

export function getParameterOptions(schema: JsonSchemaProperty): ParameterOption[] {
  const fromOptions = Array.isArray(schema.options)
    ? schema.options
      .map(normalizeParameterOption)
      .filter((option): option is ParameterOption => Boolean(option))
    : [];

  const usedValues = new Set(fromOptions.map((option) => option.value));
  const enumValues = Array.isArray(schema.enum)
    ? schema.enum
      .map((value) => String(value).trim())
      .filter((value) => value && !usedValues.has(value))
    : [];

  return [
    ...fromOptions,
    ...enumValues.map((value) => ({
      value,
      description: "",
    })),
  ];
}

export function setParameterOptions(schema: JsonObject, options: ParameterOption[]) {
  const normalizedOptions: ParameterOption[] = [];
  const usedValues = new Set<string>();
  for (const option of options) {
    const value = option.value.trim();
    if (!value || usedValues.has(value)) continue;
    usedValues.add(value);
    normalizedOptions.push({
      value,
      description: option.description.trim(),
    });
  }

  if (normalizedOptions.length === 0) {
    delete schema.enum;
    delete schema.options;
    return;
  }

  schema.enum = normalizedOptions.map((option) => option.value);
  schema.options = normalizedOptions;
}

export function formatOptionalNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

export function getArrayItemType(schema: JsonSchemaProperty) {
  const items = schema.items;
  if (!items || typeof items !== "object" || Array.isArray(items)) {
    return "string";
  }
  return asString((items as JsonObject).type, "string");
}

export function setArrayItemType(schema: JsonObject, type: string) {
  const items = toJsonObject(schema.items);
  items.type = type;
  schema.items = items;
}

export function setOptionalStringField(schema: JsonObject, key: string, value: string) {
  const normalized = value.trim();
  if (normalized) {
    schema[key] = normalized;
  } else {
    delete schema[key];
  }
}

export function setOptionalNumberField(
  schema: JsonObject,
  key: string,
  value: string,
  options: { integer?: boolean; minimum?: number } = {},
) {
  const normalized = value.trim();
  if (!normalized) {
    delete schema[key];
    return;
  }

  const parsed = options.integer
    ? Number.parseInt(normalized, 10)
    : Number(normalized);
  if (Number.isNaN(parsed)) {
    return;
  }
  schema[key] = options.minimum === undefined
    ? parsed
    : Math.max(options.minimum, parsed);
}

export function setInputParameterRequired(draft: JsonObject, name: string, isRequired: boolean) {
  const inputSchema = ensureInputSchema(draft);
  const required = new Set(asStringArray(inputSchema.required));
  if (isRequired) {
    required.add(name);
  } else {
    required.delete(name);
  }
  inputSchema.required = Array.from(required);
}

export function formatDefaultValue(value: unknown) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  return String(value);
}

export function parseDefaultValue(value: string, type: string): unknown {
  const normalized = value.trim();
  if (!normalized) return undefined;
  if (type === "integer") {
    const parsed = Number.parseInt(normalized, 10);
    return Number.isNaN(parsed) ? undefined : parsed;
  }
  if (type === "number") {
    const parsed = Number(normalized);
    return Number.isNaN(parsed) ? undefined : parsed;
  }
  if (type === "boolean") {
    if (["true", "1", "yes", "是"].includes(normalized.toLowerCase())) return true;
    if (["false", "0", "no", "否"].includes(normalized.toLowerCase())) return false;
    return undefined;
  }
  return value;
}

export function buildDefaultValueOptions(
  options: ParameterOption[],
  defaultValue: string,
): Array<{ label: string; value: string }> {
  const items: Array<{ label: string; value: string }> = [{ label: "无", value: "" }];
  const usedValues = new Set<string>([""]);

  for (const option of options) {
    const value = option.value.trim();
    if (!value || usedValues.has(value)) continue;
    usedValues.add(value);
    items.push({ label: value, value });
  }

  if (defaultValue && !usedValues.has(defaultValue)) {
    items.push({ label: defaultValue, value: defaultValue });
  }

  return items;
}

function ensureInputSchema(draft: JsonObject): JsonObject {
  const inputSchema = ensureObject(draft, "input_schema");
  if (asString(inputSchema.type) !== "object") {
    inputSchema.type = "object";
  }
  const properties = getInputProperties(inputSchema);
  inputSchema.properties = properties;
  return inputSchema;
}

function getInputProperties(inputSchema: JsonObject): Record<string, JsonObject> {
  return toJsonObject(inputSchema.properties) as Record<string, JsonObject>;
}

function normalizeParameterOption(value: unknown): ParameterOption | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const payload = value as JsonObject;
  const optionValue = asString(payload.value).trim();
  if (!optionValue) {
    return null;
  }
  return {
    value: optionValue,
    description: asString(payload.description),
  };
}

function toJsonObject(value: unknown): JsonObject {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return { ...(value as JsonObject) };
  }
  return {};
}
