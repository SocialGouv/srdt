import { push } from "@socialgouv/matomo-next";

export interface ResponseAnalyticsData {
  familyModel?: string;
  modelName?: string;
  scenarioVersion?: string;
  globalResponseTime?: number;
  inputNbTokens?: number;
  outputNbTokens?: number;
  userQuestion?: string;
  llmResponse?: string;
  errorMessage?: string;
  idcc?: string;
  isFollowupResponse?: boolean;
}

/**
 * Hash an email using SHA-256 for privacy, truncated to 24 chars
 * This allows tracking unique users without storing personal data
 */
export async function hashEmail(email: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(email.toLowerCase().trim());
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  // Truncate to 24 characters for shorter user IDs
  return hashHex.slice(0, 24);
}

/**
 * Set the Matomo User ID (email hash) for tracking
 * This should be called once when the user is identified
 * See: https://developer.matomo.org/guides/tracking-javascript-guide#user-id
 */
export function setMatomoUserId(userEmailHash: string): void {
  push(["setUserId", userEmailHash]);
}

/**
 * Reset the Matomo User ID (when user logs out)
 */
export function resetMatomoUserId(): void {
  push(["resetUserId"]);
}

/**
 * Track response analytics to Matomo
 * Called when a response is received
 *
 * Sends N separate events for each field:
 * - Category: "analytics"
 * - Action: field name (e.g., "familyModel", "modelName", etc.)
 * - Name: field value as string
 *
 * See: https://fr.matomo.org/faq/reports/the-anatomy-of-an-event/
 */
export function trackResponseAnalytics(data: ResponseAnalyticsData): void {
  const timestamp = new Date().toISOString();

  // Send separate events for each field
  push(["trackEvent", "analytics", "timestamp", timestamp]);

  if (data.familyModel) {
    push(["trackEvent", "analytics", "familyModel", data.familyModel]);
  }
  if (data.modelName) {
    push(["trackEvent", "analytics", "modelName", data.modelName]);
  }
  if (data.scenarioVersion) {
    push(["trackEvent", "analytics", "scenarioVersion", data.scenarioVersion]);
  }
  if (data.globalResponseTime !== undefined) {
    push([
      "trackEvent",
      "analytics",
      "globalResponseTime",
      String(data.globalResponseTime),
    ]);
  }
  if (data.inputNbTokens !== undefined) {
    push([
      "trackEvent",
      "analytics",
      "inputNbTokens",
      String(data.inputNbTokens),
    ]);
  }
  if (data.outputNbTokens !== undefined) {
    push([
      "trackEvent",
      "analytics",
      "outputNbTokens",
      String(data.outputNbTokens),
    ]);
  }
  if (data.userQuestion) {
    push(["trackEvent", "analytics", "userQuestion", data.userQuestion]);
  }
  if (data.llmResponse) {
    push(["trackEvent", "analytics", "llmResponse", data.llmResponse]);
  }
  if (data.errorMessage) {
    push(["trackEvent", "analytics", "errorMessage", data.errorMessage]);
  }
  if (data.idcc) {
    push(["trackEvent", "analytics", "idcc", data.idcc]);
  }
  push([
    "trackEvent",
    "analytics",
    "isFollowupResponse",
    String(data.isFollowupResponse ?? false),
  ]);
}
