"use strict";

// Return the submit label describing what the chosen radio will do.
function assessmentPickerLabel(choice, currentId) {
    if (!choice) {
        return "Link assessment";
    }
    if (choice === "new") {
        return "Create new assessment…";
    }
    if (!currentId) {
        return `Link assessment #${choice}`;
    }
    if (choice === currentId) {
        return `Keep assessment #${choice}`;
    }
    return `Switch to assessment #${choice}`;
}

// Drive a form wrapping the `assessment_picker` macro: keep its single submit
// button labelled for the chosen assessment, and send "None of these" to the
// new-assessment modal instead of the link endpoint the form posts to.
$.fn.assessmentPicker = function () {
    return this.each(function () {
        let $form = $(this);
        let $submit = $form.find(".AssessmentPicker-submit");
        let currentId = String($form.data("current-assessment") || "");
        let newModal = $form.data("new-assessment-modal");

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

            $submit.text(assessmentPickerLabel(choice, currentId));
            $submit.prop("disabled", !choice || choice === currentId);
        }

        $form.on("change", ".AssessmentPicker-radio", update);

        $form.on("submit", function (event) {
            if (chosen() !== "new") {
                return;
            }

            event.preventDefault();
            $(`.uplift-assessment-modal[data-assessment-modal="${newModal}"]`).addClass(
                "is-active",
            );
        });

        update();
    });
};
