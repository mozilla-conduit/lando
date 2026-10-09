"use strict";

import "@static_src/legacy/js/components/AssessmentPicker";

// Render a picker form with assessments #4 and #5, revealing a form for new ones.
function renderPicker() {
    document.body.innerHTML = `
        <form class="AssessmentPicker-form" data-new-assessment-reveal="#new-assessment">
            <div class="AssessmentPicker-choice">
                <input class="AssessmentPicker-radio" type="radio" name="assessment" value="4">
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

    test("reveals the new-assessment form for `None of these`", () => {
        renderPicker();

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
