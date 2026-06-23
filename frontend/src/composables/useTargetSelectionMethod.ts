/** How the uplift target was selected, recorded for analytics. */
export type TargetSelectionMethod =
  | "widget_version"
  | "widget_manual"
  | "server_rendered";

/** A bridge that records the selection method into a hidden form field. */
export interface TargetSelectionMethodField {
  /** Write the given method into the hidden input, if it is present. */
  setMethod(method: TargetSelectionMethod): void;
}

/**
 * Bridge the Vue widget to the server-rendered hidden `target_selection_method`
 * input. The widget writes how the target was selected so the submission can be
 * attributed to the widget; the field stays empty (and the server defaults it to
 * `server_rendered`) when the widget never mounts.
 *
 * @param inputSelector - Selector for the hidden input element.
 */
export function useTargetSelectionMethod(
  inputSelector = "#id_target_selection_method",
): TargetSelectionMethodField {
  const inputElement = document.querySelector<HTMLInputElement>(inputSelector);

  function setMethod(method: TargetSelectionMethod): void {
    if (inputElement) {
      inputElement.value = method;
    }
  }

  return { setMethod };
}
