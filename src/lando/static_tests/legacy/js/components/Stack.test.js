"use strict";

import "@static_src/legacy/js/components/Stack";

// Render an uplift revision's actions, with "Request Uplift" inside "More".
function renderActions() {
    document.body.innerHTML = `
        <div class="StackPage-stack"></div>
        <div class="StackPage-actions">
            <div class="dropdown StackPage-moreActions">
                <button type="button" class="StackPage-moreActions-trigger" aria-expanded="false">More</button>
                <a class="dropdown-item uplift-request-open" href="#">Uplift to another train…</a>
            </div>
        </div>
        <div class="uplift-request-modal modal"></div>
    `;
    $(".StackPage-stack").stack();
}

describe("$.fn.stack actions", () => {
    test("`More` opens and closes its menu", () => {
        renderActions();

        $(".StackPage-moreActions-trigger").trigger("click");

        expect(
            $(".StackPage-moreActions").hasClass("is-active"),
            "The menu opens.",
        ).toBe(true);
        expect(
            $(".StackPage-moreActions-trigger").attr("aria-expanded"),
            "The trigger reports it is open.",
        ).toBe("true");

        $(document.body).trigger("click");

        expect(
            $(".StackPage-moreActions").hasClass("is-active"),
            "Clicking elsewhere closes the menu.",
        ).toBe(false);
    });

    test("uplifting from the menu opens the request modal", () => {
        renderActions();
        $(".StackPage-moreActions-trigger").trigger("click");

        let clickEvent = $.Event("click");
        $(".uplift-request-open").trigger(clickEvent);

        expect(clickEvent.isDefaultPrevented(), "The `#` link is not followed.").toBe(
            true,
        );
        expect(
            $(".uplift-request-modal").hasClass("is-active"),
            "The uplift request modal opens.",
        ).toBe(true);
        expect(
            $(".StackPage-moreActions").hasClass("is-active"),
            "The menu closes behind the modal.",
        ).toBe(false);
    });
});
