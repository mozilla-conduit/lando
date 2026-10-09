"use strict";

import "@static_src/legacy/js/components/AssessmentPicker";

// Render a picker form with assessments #4 and #5, optionally linked to one. The
// revision page answers "None of these" with a modal; the batch page reveals a form.
function renderPicker(currentId = "", { reveal = false } = {}) {
    let newAssessment = reveal
        ? 'data-new-assessment-reveal="#new-assessment"'
        : 'data-new-assessment-modal="new"';
    document.body.innerHTML = `
        <form class="AssessmentPicker-form" data-current-assessment="${currentId}" data-revision-id="4218" ${newAssessment}>
            <div class="AssessmentPicker-choice">
                <input class="AssessmentPicker-radio" type="radio" name="assessment" value="4"${currentId === "4" ? " checked" : ""}>
            </div>
            <div class="AssessmentPicker-choice">
                <input class="AssessmentPicker-radio" type="radio" name="assessment" value="5">
            </div>
            <div class="AssessmentPicker-choice">
                <input class="AssessmentPicker-radio" type="radio" name="assessment" value="new">
            </div>
            <div class="AssessmentPicker-actions">
                <button type="submit" class="AssessmentPicker-submit">Link assessment</button>
            </div>
        </form>
        <div class="uplift-assessment-modal" data-assessment-modal="new"></div>
        <form id="new-assessment" hidden></form>
    `;
    $(".AssessmentPicker-form").assessmentPicker();
}

function choose(value) {
    $(`.AssessmentPicker-radio[value="${value}"]`)
        .prop("checked", true)
        .trigger("change");
}

describe("$.fn.assessmentPicker", () => {
    test("waits for a choice before it can link", () => {
        renderPicker();

        expect(
            $(".AssessmentPicker-submit").prop("disabled"),
            "Nothing is chosen yet.",
        ).toBe(true);

        choose("5");

        expect(
            $(".AssessmentPicker-submit").text(),
            "The label names the assessment.",
        ).toBe("Link assessment #5");
        expect(
            $(".AssessmentPicker-submit").prop("disabled"),
            "A choice enables it.",
        ).toBe(false);
        expect(
            $('.AssessmentPicker-radio[value="5"]')
                .closest(".AssessmentPicker-choice")
                .hasClass("is-selected"),
            "The chosen assessment is highlighted.",
        ).toBe(true);
    });

    test("labels a switch away from the linked assessment", () => {
        renderPicker("4");

        expect(
            $(".AssessmentPicker-submit").text(),
            "Keeping the link does nothing.",
        ).toBe("Keep assessment #4");
        expect(
            $(".AssessmentPicker-submit").prop("disabled"),
            "Keeping is not a change.",
        ).toBe(true);

        choose("5");

        expect(
            $(".AssessmentPicker-submit").text(),
            "Choosing another one switches.",
        ).toBe("Switch to assessment #5");
    });

    test("cancelling puts the choice back on the linked assessment", () => {
        renderPicker("4");
        let cancelled = vi.fn();
        $(".AssessmentPicker-form").on("assessmentpicker:cancel", cancelled);
        $(".AssessmentPicker-form").append(
            '<button type="button" class="AssessmentPicker-cancel">Cancel</button>',
        );
        choose("5");

        $(".AssessmentPicker-cancel").trigger("click");

        expect(
            $('.AssessmentPicker-radio[value="4"]').prop("checked"),
            "The linked assessment is chosen again.",
        ).toBe(true);
        expect(
            $(".AssessmentPicker-submit").text(),
            "The label goes back to keeping it.",
        ).toBe("Keep assessment #4");
        expect(cancelled, "The picker says it was cancelled.").toHaveBeenCalledTimes(1);
    });

    test("opens the new-assessment modal for `None of these`", () => {
        renderPicker();
        choose("new");

        expect(
            $(".AssessmentPicker-submit").text(),
            "The label says it creates one.",
        ).toBe("Create new assessment…");

        let submitEvent = $.Event("submit");
        $(".AssessmentPicker-form").trigger(submitEvent);

        expect(
            submitEvent.isDefaultPrevented(),
            "The link endpoint is not posted to.",
        ).toBe(true);
        expect(
            $('.uplift-assessment-modal[data-assessment-modal="new"]').hasClass(
                "is-active",
            ),
            "The new-assessment modal opens.",
        ).toBe(true);
    });

    test("links straight away when nothing is linked yet", () => {
        renderPicker();
        let submit = vi
            .spyOn(HTMLFormElement.prototype, "submit")
            .mockImplementation(() => {});
        choose("5");

        $(".AssessmentPicker-form").trigger("submit");

        expect(submit, "The link is posted without asking.").toHaveBeenCalledTimes(1);
        expect($(".AssessmentPicker-confirm").length, "Nothing is moved.").toBe(0);
        submit.mockRestore();
    });

    test("confirms before switching away from the linked assessment", () => {
        renderPicker("4");
        let submit = vi
            .spyOn(HTMLFormElement.prototype, "submit")
            .mockImplementation(() => {});
        choose("5");

        let submitEvent = $.Event("submit");
        $(".AssessmentPicker-form").trigger(submitEvent);

        expect(submitEvent.isDefaultPrevented(), "The switch waits.").toBe(true);
        expect(
            $(".AssessmentPicker-confirm-question").text(),
            "The question names both assessments.",
        ).toBe("Move D4218 from #4 to #5?");

        $(".AssessmentPicker-confirm-move").trigger("click");

        expect(submit, "Confirming posts the switch.").toHaveBeenCalledTimes(1);
        submit.mockRestore();
    });

    test("cancelling the confirmation keeps the form as it was", () => {
        renderPicker("4");
        choose("5");
        $(".AssessmentPicker-form").trigger($.Event("submit"));

        $(".AssessmentPicker-confirm-cancel").trigger("click");

        expect($(".AssessmentPicker-confirm").length, "The question goes away.").toBe(
            0,
        );
        expect(
            $(".AssessmentPicker-submit").prop("disabled"),
            "The switch can be submitted again.",
        ).toBe(false);
    });

    test("reveals the new-assessment form for `None of these`", () => {
        renderPicker("", { reveal: true });

        choose("new");

        expect($("#new-assessment").prop("hidden"), "The questions appear.").toBe(
            false,
        );
        expect(
            $(".AssessmentPicker-actions").prop("hidden"),
            "The link button steps aside for the form's own.",
        ).toBe(true);

        let submitEvent = $.Event("submit");
        $(".AssessmentPicker-form").trigger(submitEvent);
        expect(
            submitEvent.isDefaultPrevented(),
            "`None of these` is not posted to the link endpoint.",
        ).toBe(true);

        choose("4");

        expect($("#new-assessment").prop("hidden"), "The questions go away.").toBe(
            true,
        );
        expect(
            $(".AssessmentPicker-actions").prop("hidden"),
            "The link button comes back.",
        ).toBe(false);
    });
});
