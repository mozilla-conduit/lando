import { describe, it, expect, afterEach } from "vitest";
import { useTargetSelectionMethod } from "@/composables/useTargetSelectionMethod";

function renderHiddenField(): HTMLInputElement {
    document.body.innerHTML = `
    <input type="hidden" id="id_target_selection_method" name="target_selection_method">
  `;
    return document.querySelector<HTMLInputElement>("#id_target_selection_method")!;
}

afterEach(() => {
    document.body.innerHTML = "";
});

describe("useTargetSelectionMethod", () => {
    it("writes the method into the hidden input", () => {
        const input = renderHiddenField();

        const field = useTargetSelectionMethod();
        field.setMethod("widget_version");

        expect(input.value).toBe("widget_version");
    });

    it("overwrites a previously recorded method", () => {
        const input = renderHiddenField();

        const field = useTargetSelectionMethod();
        field.setMethod("widget_version");
        field.setMethod("widget_manual");

        expect(input.value).toBe("widget_manual");
    });

    it("is a no-op when the hidden input is absent", () => {
        const field = useTargetSelectionMethod();

        // Should not throw even though no matching element exists.
        expect(() => field.setMethod("server_rendered")).not.toThrow();
    });
});
