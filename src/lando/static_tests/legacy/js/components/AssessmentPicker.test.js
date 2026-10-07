"use strict";

import "@static_src/legacy/js/components/AssessmentPicker";

// Render a picker form with assessments #4 and #5, optionally linked to one.
function renderPicker(currentId = "") {
    document.body.innerHTML = `
        <form class="AssessmentPicker-form" data-current-assessment="${currentId}" data-new-assessment-modal="new">
            <div class="AssessmentPicker-choice">
                <input class="AssessmentPicker-radio" type="radio" name="assessment" value="4"${currentId === "4" ? " checked" : ""}>
            </div>
            <div class="AssessmentPicker-choice">
                <input class="AssessmentPicker-radio" type="radio" name="assessment" value="5">
            </div>
            <div class="AssessmentPicker-choice">
                <input class="AssessmentPicker-radio" type="radio" name="assessment" value="new">
            </div>
            <button type="submit" class="AssessmentPicker-submit">Link assessment</button>
        </form>
        <div class="uplift-assessment-modal" data-assessment-modal="new"></div>
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
});
