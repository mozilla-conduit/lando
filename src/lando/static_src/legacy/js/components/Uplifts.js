"use strict";

$.fn.uplifts = function () {
    return this.each(function () {
        let $uplifts = $(this);

        // Format timestamps.
        $uplifts.find("time[data-timestamp]").formatTime();

        // Ensure all toggle content is hidden on page load.
        $uplifts.find(".uplift-toggle-content").hide();

        // Show or hide the assessment picker behind the checklist's "Change".
        $uplifts.on("click", ".UpliftReadiness-toggle", function () {
            let $toggle = $(this);
            let expanded = $toggle.attr("aria-expanded") === "true";

            $(`#${$toggle.attr("aria-controls")}`).prop("hidden", expanded);
            $toggle.attr("aria-expanded", String(!expanded));
        });

        // Cancelling a change closes the picker it was made in.
        $uplifts.on("assessmentpicker:cancel", ".AssessmentPicker-form", function () {
            let $expand = $(this).closest(".UpliftReadiness-expand");

            $expand.prop("hidden", true);
            $uplifts
                .find(`.UpliftReadiness-toggle[aria-controls="${$expand.attr("id")}"]`)
                .attr("aria-expanded", "false");
        });

        // Handle toggle for error details and command sections.
        $uplifts.on("click", ".uplift-toggle", function (e) {
            e.preventDefault();

            let $button = $(this);
            let targetId = $button.data("toggle-target");

            // Find the content section with matching data-toggle-id.
            let $targetContent = $uplifts.find(
                `.uplift-toggle-content[data-toggle-id="${targetId}"]`,
            );

            // Check if content is currently visible.
            let isVisible = $targetContent.is(":visible");

            // Toggle the visibility of the target content.
            $targetContent.toggle();

            // Find all buttons with the same target that are NOT inside the content.
            // These are the "Show" buttons.
            let $showButtons = $uplifts
                .find(`.uplift-toggle[data-toggle-target="${targetId}"]`)
                .not($targetContent.find(".uplift-toggle"));

            // Find all buttons with the same target (including inside content).
            let $allButtons = $uplifts.find(
                `.uplift-toggle[data-toggle-target="${targetId}"]`,
            );

            // Update aria-expanded attributes for all related buttons.
            if (isVisible) {
                // Content is being hidden.
                $showButtons.show().attr("aria-expanded", "false");
                $targetContent.find(".uplift-toggle").attr("aria-expanded", "false");
            } else {
                // Content is being shown.
                $showButtons.hide().attr("aria-expanded", "true");
                $targetContent.find(".uplift-toggle").attr("aria-expanded", "true");
            }
        });
    });
};
