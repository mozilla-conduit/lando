"use strict";


$.fn.stack = function () {
    return this.each(function () {
        let $stack = $(this);
        let $radio = $stack.find(".StackPage-revision-land-radio");

        $radio.on("click", (e) => {
            window.location.href = "/" + e.target.id;
            $radio.attr({ disabled: true });
        });

        // Show the uplift request form modal when the "Request Uplift" button is clicked.
        $(".uplift-request-open").on("click", function () {
            $(".uplift-request-modal").addClass("is-active");
        });
        $(".uplift-request-close").on("click", function () {
            $(".uplift-request-modal").removeClass("is-active");
        });

        // Show the assessment edit form modal when the "Request Uplift" button is clicked.
        $(".edit-assessment-open").on("click", function () {
            $(".uplift-assessment-edit-modal").addClass("is-active");
        });
        $(".edit-assessment-close").on("click", function () {
            $(".uplift-assessment-edit-modal").removeClass("is-active");
        });

        // Show the modal to link an existing uplift assessment.
        $(".link-assessment-open").on("click", function () {
            $(".uplift-assessment-link-modal").addClass("is-active");
        });
        $(".link-assessment-close").on("click", function () {
            $(".uplift-assessment-link-modal").removeClass("is-active");
        });
        function updateQeStepsRequired(form) {
            let selectedRadio = form.find(
                'input[name="needs_manual_qe_testing"]:checked',
            );
            let stepsTextarea = form.find(
                'textarea[name="qe_testing_reproduction_steps"]',
            );
            stepsTextarea.prop("required", selectedRadio.val() === "yes");
        }

        $('input[name="needs_manual_qe_testing"]').on("change", function () {
            updateQeStepsRequired($(this).closest("form"));
        });

        // Set the initial `required` state for any pre-populated forms.
        $('input[name="needs_manual_qe_testing"]')
            .closest("form")
            .each(function () {
                updateQeStepsRequired($(this));
            });

        // Require at least one repository checkbox to be selected in the uplift
        // request form. Since `required` on `CheckboxSelectMultiple` would require
        // all checkboxes to be checked, we use `setCustomValidity` instead.
        let repositoryCheckboxes = $('input[name="repositories"]');

        function updateRepositoryValidity() {
            let isAnyChecked = repositoryCheckboxes.is(":checked");
            let validityMessage = isAnyChecked
                ? ""
                : "Please select at least one repository.";
            repositoryCheckboxes.each(function () {
                this.setCustomValidity(validityMessage);
            });
        }

        repositoryCheckboxes.on("change", updateRepositoryValidity);
        updateRepositoryValidity();

    })
};