"use strict";

// Return the submit label describing what the chosen radio will do.
function assessmentPickerLabel(choice) {
    if (!choice) {
        return "Link assessment";
    }
    if (choice === "new") {
        return "Create new assessment…";
    }
    return `Link assessment #${choice}`;
}

// Drive a form wrapping the `assessment_picker` macro: keep its single submit
// button labelled for the chosen assessment, and reveal the new-assessment form
// for "None of these" instead of posting to the link endpoint.
$.fn.assessmentPicker = function () {
    return this.each(function () {
        let $form = $(this);
        let $submit = $form.find(".AssessmentPicker-submit");
        let $newReveal = $($form.data("new-assessment-reveal") || []);

        function chosen() {
            return $form.find(".AssessmentPicker-radio:checked").val() || "";
        }

        function update() {
            let choice = chosen();

            $form.find(".AssessmentPicker-choice").each(function () {
                let $choice = $(this);
                $choice.toggleClass(
                    "is-selected",
                    $choice.find(".AssessmentPicker-radio").is(":checked"),
                );
            });

            $submit.text(assessmentPickerLabel(choice));
            $submit.prop("disabled", !choice);

            // A revealed form has its own submit button, so the link one steps aside.
            if ($newReveal.length) {
                $newReveal.prop("hidden", choice !== "new");
                $form
                    .find(".AssessmentPicker-actions")
                    .prop("hidden", choice === "new");
            }
        }

        $form.on("change", ".AssessmentPicker-radio", update);

        // "None of these" is answered by the revealed form, not the link endpoint.
        $form.on("submit", function (event) {
            if (chosen() === "new") {
                event.preventDefault();
            }
        });

        update();
    });
};
