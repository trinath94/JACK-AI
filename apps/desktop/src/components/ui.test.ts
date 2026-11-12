import { describe, expect, it } from "vitest";
import { formatBytes, usd } from "./ui";

describe("usd", () => {
  it("shows enough places for single-request amounts", () => {
    expect(usd("0.000148")).toBe("$0.000148");
    expect(usd("0.0042")).toBe("$0.0042");
  });
  it("uses cents for normal amounts and dashes for unknown", () => {
    expect(usd("12")).toBe("$12.00");
    expect(usd("1.2345")).toBe("$1.2345");
    expect(usd("0")).toBe("$0.00");
    expect(usd(null)).toBe("—");
  });
});

describe("formatBytes", () => {
  it("scales units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(16 * 1024 ** 3)).toBe("16 GB");
  });
});
