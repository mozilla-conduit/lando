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

// Drive a form wrapping the `assessment_picker` macro: label its submit button
// for the chosen assessment, answer "None of these" without posting, and
// confirm before moving a revision off the assessment it is linked to.
$.fn.assessmentPicker = function () {
    return this.each(function () {
        let $form = $(this);
        let $submit = $form.find(".AssessmentPicker-submit");
        let currentId = String($form.data("current-assessment") || "");
        let newModal = $form.data("new-assessment-modal");
        let $newReveal = $($form.data("new-assessment-reveal") || []);
        let revisionId = $form.data("revision-id");

        function chosen() {
            return $form.find(".AssessmentPicker-radio:checked").val() || "";
        }

        function update() {
            let choice = chosen();

            $form.find(".AssessmentPicker-confirm").remove();

            $submit.text(assessmentPickerLabel(choice, currentId));
            $submit.prop("disabled", !choice || choice === currentId);

            // A revealed form has its own submit button, so the link one steps aside.
            if ($newReveal.length) {
                $newReveal.prop("hidden", choice !== "new");
                $form
                    .find(".AssessmentPicker-actions")
                    .prop("hidden", choice === "new");
            }
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
        // The question stays inline rather than modal, so changing the choice
        // simply dismisses it; focus moves to it so keyboard users notice it.
        function confirmSwitch(choice) {
            // Every interpolated value is a numeric ID the server rendered.
            $submit.prop("disabled", true);
            $form.append(`
                <article class="message is-warning AssessmentPicker-confirm mt-3"
                         role="alertdialog"
                         aria-labelledby="AssessmentPicker-confirm-question-${revisionId}"
                         aria-describedby="AssessmentPicker-confirm-detail-${revisionId}">
                    <div class="message-body">
                        <p id="AssessmentPicker-confirm-question-${revisionId}" class="AssessmentPicker-confirm-question has-text-weight-semibold">Move D${revisionId} from #${currentId} to #${choice}?</p>
                        <p id="AssessmentPicker-confirm-detail-${revisionId}" class="is-size-7">#${currentId} will no longer cover D${revisionId}.</p>
                        <div class="buttons mt-2">
                            <button type="button" class="button is-small is-warning AssessmentPicker-confirm-move">Move to #${choice}</button>
                            <button type="button" class="button is-small AssessmentPicker-confirm-cancel">Cancel</button>
                        </div>
                    </div>
                </article>
            `);
            $form.find(".AssessmentPicker-confirm-move").trigger("focus");
        }

        $form.on("click", ".AssessmentPicker-confirm-move", function () {
            $form.get(0).submit();
        });

        $form.on("click", ".AssessmentPicker-confirm-cancel", update);

        // "None of these" is answered by the new-assessment modal or the revealed
        // form, not the link endpoint, and a switch waits to be confirmed.
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
