import { describe, expect, it } from "vitest";

import { ConfigError, parseServerConfig } from "./config";

describe("parseServerConfig", () => {
  it("accepts an http URL and normalizes the trailing slash", () => {
    expect(parseServerConfig({ RELAY_API_URL: "http://api:8000" }).apiBaseUrl.href).toBe(
      "http://api:8000/",
    );
    expect(
      parseServerConfig({ RELAY_API_URL: " https://relay.example/api " }).apiBaseUrl.href,
    ).toBe("https://relay.example/api/");
  });

  it.each([
    [undefined, "not set"],
    ["", "not set"],
    ["api:8000", "http or https"],
    ["not a url", "valid absolute URL"],
    ["ftp://api:8000", "http or https"],
    ["javascript:alert(1)", "http or https"],
    ["http://user:pass@api:8000", "credentials"],
    ["http://api:8000/?x=1", "query string"],
    ["http://api:8000/#frag", "query string"],
  ])("rejects %j", (value, message) => {
    expect(() => parseServerConfig({ RELAY_API_URL: value })).toThrow(ConfigError);
    expect(() => parseServerConfig({ RELAY_API_URL: value })).toThrow(message);
  });
});
