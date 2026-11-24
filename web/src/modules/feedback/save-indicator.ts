/**
 * Sends an indicator (time saved, NPS…) to the save route. Fire-and-forget:
 * a failure must never break the UI.
 */
export const saveIndicator = async (
  body: { action: "save_time_saved" | "save_nps" } & Record<string, unknown>
): Promise<void> => {
  try {
    await fetch("/api/conversations/save", {
      method: "POST",
      // The NPS modal closes right after: let the request outlive it.
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    console.error(`Failed to save indicator (${body.action}):`, error);
  }
};
