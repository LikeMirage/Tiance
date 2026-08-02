export type ParsedThemeColor = {
  alpha: number | null;
  blue: number;
  format: "hex" | "hex-alpha" | "rgb" | "rgba";
  green: number;
  red: number;
};

const HEX_COLOR_PATTERN = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
const RGB_COLOR_PATTERN =
  /^rgba?\(\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)(?:\s*,\s*([+-]?\d*(?:\.\d+)?%?))?\s*\)$/i;

export function parseThemeColorValue(value: string): ParsedThemeColor | null {
  const normalized = value.trim();
  if (!normalized) return null;

  const hexMatch = normalized.match(HEX_COLOR_PATTERN);
  if (hexMatch) {
    return parseHexColor(hexMatch[1]);
  }

  const rgbMatch = normalized.match(RGB_COLOR_PATTERN);
  if (rgbMatch) {
    const alpha = rgbMatch[4] === undefined ? null : parseAlpha(rgbMatch[4]);
    return {
      alpha,
      blue: clampByte(Number(rgbMatch[3])),
      format: alpha === null ? "rgb" : "rgba",
      green: clampByte(Number(rgbMatch[2])),
      red: clampByte(Number(rgbMatch[1])),
    };
  }

  return null;
}

export function toColorPickerValue(value: string): string | null {
  const parsed = parseThemeColorValue(value);
  if (!parsed) return null;
  return toHexColor(parsed.red, parsed.green, parsed.blue);
}

export function applyColorPickerValue(currentValue: string, pickerValue: string): string {
  const picked = parseThemeColorValue(pickerValue);
  if (!picked) return currentValue;

  const current = parseThemeColorValue(currentValue);
  if (!current) return toHexColor(picked.red, picked.green, picked.blue);

  if (current.format === "rgba") {
    return `rgba(${picked.red}, ${picked.green}, ${picked.blue}, ${formatAlpha(current.alpha)})`;
  }

  if (current.format === "rgb") {
    return `rgb(${picked.red}, ${picked.green}, ${picked.blue})`;
  }

  if (current.format === "hex-alpha") {
    return `${toHexColor(picked.red, picked.green, picked.blue)}${alphaToHex(current.alpha)}`;
  }

  return toHexColor(picked.red, picked.green, picked.blue);
}

function parseHexColor(hex: string): ParsedThemeColor {
  if (hex.length === 3 || hex.length === 4) {
    const red = parseInt(hex[0] + hex[0], 16);
    const green = parseInt(hex[1] + hex[1], 16);
    const blue = parseInt(hex[2] + hex[2], 16);
    const alpha = hex.length === 4 ? parseInt(hex[3] + hex[3], 16) / 255 : null;
    return {
      alpha,
      blue,
      format: alpha === null ? "hex" : "hex-alpha",
      green,
      red,
    };
  }

  const red = parseInt(hex.slice(0, 2), 16);
  const green = parseInt(hex.slice(2, 4), 16);
  const blue = parseInt(hex.slice(4, 6), 16);
  const alpha = hex.length === 8 ? parseInt(hex.slice(6, 8), 16) / 255 : null;
  return {
    alpha,
    blue,
    format: alpha === null ? "hex" : "hex-alpha",
    green,
    red,
  };
}

function parseAlpha(value: string): number {
  if (value.endsWith("%")) {
    return clamp(Number(value.slice(0, -1)) / 100, 0, 1);
  }
  return clamp(Number(value), 0, 1);
}

function formatAlpha(alpha: number | null): string {
  if (alpha === null) return "1";
  return Number(alpha.toFixed(3)).toString();
}

function alphaToHex(alpha: number | null): string {
  if (alpha === null) return "ff";
  return clampByte(alpha * 255).toString(16).padStart(2, "0");
}

function toHexColor(red: number, green: number, blue: number): string {
  return `#${clampByte(red).toString(16).padStart(2, "0")}${clampByte(green)
    .toString(16)
    .padStart(2, "0")}${clampByte(blue).toString(16).padStart(2, "0")}`;
}

function clampByte(value: number): number {
  return Math.round(clamp(value, 0, 255));
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}
