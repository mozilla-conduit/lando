'use strict';

$.fn.uplifts = function() {
  return this.each(function() {
    let $uplifts = $(this);

    // Format timestamps.
    $uplifts.find('time[data-timestamp]').formatTime();

    // Ensure all toggle content is hidden on page load.
    $uplifts.find('.uplift-toggle-content').hide();

    // Handle toggle for error details and command sections.
    $uplifts.on('click', '.uplift-toggle', function(e) {
      e.preventDefault();

      let $button = $(this);
      let targetId = $button.data('toggle-target');

      // Find the content section with matching data-toggle-id.
      let $targetContent = $uplifts.find(`.uplift-toggle-content[data-toggle-id="${targetId}"]`);

      // Check if content is currently visible.
      let isVisible = $targetContent.is(':visible');

      // Toggle the visibility of the target content.
      $targetContent.toggle();

      // Find all buttons with the same target that are NOT inside the content.
      // These are the "Show" buttons.
      let $showButtons = $uplifts.find(`.uplift-toggle[data-toggle-target="${targetId}"]`).not($targetContent.find('.uplift-toggle'));

      // Find all buttons with the same target (including inside content).
      let $allButtons = $uplifts.find(`.uplift-toggle[data-toggle-target="${targetId}"]`);

      // Update aria-expanded attributes for all related buttons.
      if (isVisible) {
        // Content is being hidden.
        $showButtons.show().attr('aria-expanded', 'false');
        $targetContent.find('.uplift-toggle').attr('aria-expanded', 'false');
      } else {
        // Content is being shown.
        $showButtons.hide().attr('aria-expanded', 'true');
        $targetContent.find('.uplift-toggle').attr('aria-expanded', 'true');
      }
    });
  });
};
