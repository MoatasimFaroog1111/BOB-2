export const SMART_ACCOUNTANT_UI_ACTION_EVENT = "guardian:smart-accountant-ui-action";

export type SmartAccountantUiAction =
  | { type: "prompt"; prompt: string }
  | { type: "analyze-document" };

export function emitSmartAccountantUiAction(action: SmartAccountantUiAction) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<SmartAccountantUiAction>(SMART_ACCOUNTANT_UI_ACTION_EVENT, {
      detail: action,
    }),
  );
}
