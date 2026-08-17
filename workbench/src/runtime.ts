export interface WorkbenchRuntimeConfig {
  profile: "local";
  apiBaseUrl: string;
  identity: string;
}

interface RuntimeConfigPayload {
  profile?: unknown;
  api_base_url?: unknown;
  identity?: unknown;
}

const isRecord = (value: unknown): value is RuntimeConfigPayload =>
  typeof value === "object" && value !== null;

export const loadRuntimeConfig = async (
  fetcher: typeof fetch = fetch,
): Promise<WorkbenchRuntimeConfig> => {
  const response = await fetcher("/runtime-config");
  const body = (await response.json().catch(() => null)) as unknown;

  if (!response.ok) {
    throw new Error(`Unable to load local runtime configuration (${response.status})`);
  }

  if (
    !isRecord(body) ||
    body.profile !== "local" ||
    typeof body.api_base_url !== "string" ||
    typeof body.identity !== "string" ||
    !body.identity.trim()
  ) {
    throw new Error("Invalid local runtime configuration");
  }

  return {
    profile: "local",
    apiBaseUrl: body.api_base_url,
    identity: body.identity,
  };
};
