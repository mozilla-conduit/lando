"use strict";

import "@static_src/legacy/js/components/Stack";

// Render two assessment modals, each with the button that opens it.
function renderAssessmentModals() {
    document.body.innerHTML = `
        <div class="StackPage-stack"></div>
        <button class="assessment-modal-open" data-assessment-modal="12">Edit</button>
        <button class="assessment-modal-open" data-assessment-modal="new">Create</button>
        <div class="uplift-assessment-modal modal" data-assessment-modal="12">
            <button class="assessment-modal-close" type="button">Cancel</button>
        </div>
        <div class="uplift-assessment-modal modal" data-assessment-modal="new">
            <button class="assessment-modal-close" type="button">Cancel</button>
        </div>
    `;
    $(".StackPage-stack").stack();
}

// Return whether the assessment modal with the given id is open.
function isModalOpen(modalId) {
    return $(`.uplift-assessment-modal[data-assessment-modal="${modalId}"]`).hasClass(
        "is-active",
    );
}

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

describe("$.fn.stack assessment modals", () => {
    test("each button opens the modal it names", () => {
        renderAssessmentModals();

        $('.assessment-modal-open[data-assessment-modal="new"]').trigger("click");

        expect(isModalOpen("new"), "The named modal opens.").toBe(true);
        expect(isModalOpen("12"), "The other modal stays closed.").toBe(false);
    });

    test("cancelling closes only its own modal", () => {
        renderAssessmentModals();
        $(".assessment-modal-open").trigger("click");

        $(
            '.uplift-assessment-modal[data-assessment-modal="12"] .assessment-modal-close',
        ).trigger("click");

        expect(isModalOpen("12"), "The cancelled modal closes.").toBe(false);
        expect(isModalOpen("new"), "The other modal stays open.").toBe(true);
    });
});

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
