"use strict";

import "@static_src/legacy/js/utils/formatTime";
import "@static_src/legacy/js/components/AssessmentPicker";
import "@static_src/legacy/js/components/Uplifts";

// Render a checklist whose picker, linked to assessment #4, sits behind "Change".
function renderChecklist() {
    document.body.innerHTML = `
        <div class="Uplifts">
            <button type="button" class="UpliftReadiness-toggle" aria-expanded="false" aria-controls="uplift-assessment-picker">Change</button>
            <ul>
                <li class="UpliftReadiness-expand" id="uplift-assessment-picker" hidden>
                    <form class="AssessmentPicker-form" data-current-assessment="4">
                        <div class="AssessmentPicker-choice">
                            <input class="AssessmentPicker-radio" type="radio" name="assessment" value="4" checked>
                        </div>
                        <div class="AssessmentPicker-choice">
                            <input class="AssessmentPicker-radio" type="radio" name="assessment" value="5">
                        </div>
                        <button type="submit" class="AssessmentPicker-submit"></button>
                        <button type="button" class="AssessmentPicker-cancel">Cancel</button>
                    </form>
                </li>
            </ul>
        </div>
    `;
    $(".AssessmentPicker-form").assessmentPicker();
    $(".Uplifts").uplifts();
}

describe("$.fn.uplifts checklist", () => {
    test("`Change` opens the assessment picker", () => {
        renderChecklist();

        $(".UpliftReadiness-toggle").trigger("click");

        expect($("#uplift-assessment-picker").prop("hidden"), "The picker shows.").toBe(
            false,
        );
        expect(
            $(".UpliftReadiness-toggle").attr("aria-expanded"),
            "The toggle reports it is open.",
        ).toBe("true");
    });

    test("cancelling closes the picker and keeps the linked assessment", () => {
        renderChecklist();
        $(".UpliftReadiness-toggle").trigger("click");
        $('.AssessmentPicker-radio[value="5"]').prop("checked", true).trigger("change");

        $(".AssessmentPicker-cancel").trigger("click");

        expect(
            $("#uplift-assessment-picker").prop("hidden"),
            "The picker closes.",
        ).toBe(true);
        expect(
            $('.AssessmentPicker-radio[value="4"]').prop("checked"),
            "The choice goes back to the linked assessment.",
        ).toBe(true);
        expect(
            $(".UpliftReadiness-toggle").attr("aria-expanded"),
            "The toggle reports it is closed.",
        ).toBe("false");
    });

    test("the checklist toggle relabels itself", () => {
        document.body.innerHTML = `
            <div class="Uplifts">
                <button type="button" class="UpliftReadiness-toggle" aria-expanded="false" aria-controls="uplift-readiness-items" data-label-expanded="Hide checklist" data-label-collapsed="Show checklist">Show checklist</button>
                <ul id="uplift-readiness-items" hidden></ul>
            </div>
        `;
        $(".Uplifts").uplifts();

        $(".UpliftReadiness-toggle").trigger("click");

        expect($("#uplift-readiness-items").prop("hidden"), "The items show.").toBe(
            false,
        );
        expect(
            $(".UpliftReadiness-toggle").text(),
            "The label offers to hide them.",
        ).toBe("Hide checklist");

        $(".UpliftReadiness-toggle").trigger("click");

        expect(
            $(".UpliftReadiness-toggle").text(),
            "The label offers to show them.",
        ).toBe("Show checklist");
    });
});
