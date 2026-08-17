import { describe, expect, it, vi } from "vitest";

import { ShipyardApiClient } from "./api";
import { loadRuntimeConfig } from "./runtime";

const jsonResponse = (body: unknown, status = 200): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as Response;

describe("local Workbench runtime bootstrap", () => {
  it("loads the local runtime configuration from the same-origin endpoint", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({
          profile: "local",
          api_base_url: "",
          identity: "alice",
        }),
      );

    await expect(loadRuntimeConfig(fetcher as unknown as typeof fetch)).resolves.toEqual({
      profile: "local",
      apiBaseUrl: "",
      identity: "alice",
    });
    expect(fetcher).toHaveBeenCalledWith("/runtime-config");
  });

  it("rejects a non-local or incomplete runtime configuration", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({
          profile: "production",
          api_base_url: "http://example.invalid",
          identity: "",
        }),
      );

    await expect(
      loadRuntimeConfig(fetcher as unknown as typeof fetch),
    ).rejects.toThrow("local runtime configuration");
  });

  it("injects the owner identity and API base URL into API requests", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", fetcher);

    const api = new ShipyardApiClient({
      apiBaseUrl: "http://127.0.0.1:3080/",
      identity: "alice",
    });

    await expect(api.listWorkspaces()).resolves.toEqual([]);
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:3080/workspaces",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const requestInit = fetcher.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(requestInit.headers).get("X-Shipyard-Identity")).toBe(
      "alice",
    );
  });

  it("does not send an API request without a runtime identity", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const api = new ShipyardApiClient({ apiBaseUrl: "", identity: "" });

    await expect(api.listWorkspaces()).rejects.toThrow("runtime identity");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
