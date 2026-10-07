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
// button labelled for the chosen assessment, send "None of these" to the
// new-assessment modal instead of the link endpoint the form posts to, and
// confirm before moving a revision off the assessment it is linked to.
$.fn.assessmentPicker = function () {
    return this.each(function () {
        let $form = $(this);
        let $submit = $form.find(".AssessmentPicker-submit");
        let currentId = String($form.data("current-assessment") || "");
        let newModal = $form.data("new-assessment-modal");
        let revisionId = $form.data("revision-id");

        function chosen() {
            return $form.find(".AssessmentPicker-radio:checked").val() || "";
        }

        function update() {
            let choice = chosen();

            $form.find(".AssessmentPicker-confirm").remove();

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

        $form.on("click", ".AssessmentPicker-cancel", function () {
            // Put the choice back on the linked assessment before closing.
            $form
                .find(`.AssessmentPicker-radio[value="${currentId}"]`)
                .prop("checked", true);
            update();
            $form.trigger("assessmentpicker:cancel");
        });

        // Ask before switching, since the previous assessment loses this revision.
        function confirmSwitch(choice) {
            let $confirm = $(`
                <article class="message is-warning AssessmentPicker-confirm mt-3">
                    <div class="message-body">
                        <p class="AssessmentPicker-confirm-question has-text-weight-semibold"></p>
                        <p class="AssessmentPicker-confirm-detail is-size-7"></p>
                        <div class="buttons mt-2">
                            <button type="button" class="button is-small is-warning AssessmentPicker-confirm-move"></button>
                            <button type="button" class="button is-small AssessmentPicker-confirm-cancel">Cancel</button>
                        </div>
                    </div>
                </article>
            `);
            $confirm
                .find(".AssessmentPicker-confirm-question")
                .text(`Move D${revisionId} from #${currentId} to #${choice}?`);
            $confirm
                .find(".AssessmentPicker-confirm-detail")
                .text(`#${currentId} will no longer cover D${revisionId}.`);
            $confirm.find(".AssessmentPicker-confirm-move").text(`Move to #${choice}`);

            $submit.prop("disabled", true);
            $form.append($confirm);
        }

        $form.on("click", ".AssessmentPicker-confirm-move", function () {
            $form.get(0).submit();
        });

        $form.on("click", ".AssessmentPicker-confirm-cancel", update);

        $form.on("submit", function (event) {
            let choice = chosen();

            if (choice === "new") {
                event.preventDefault();
                $(
                    `.uplift-assessment-modal[data-assessment-modal="${newModal}"]`,
                ).addClass("is-active");
            } else if (currentId && choice !== currentId) {
                event.preventDefault();
                confirmSwitch(choice);
            }
        });

        update();
    });
};
