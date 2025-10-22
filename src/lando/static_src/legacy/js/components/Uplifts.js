'use strict';

$.fn.uplifts = function() {
  return this.each(function() {
    let $uplifts = $(this);

    // Format timestamps
    $uplifts.find('time[data-timestamp]').formatTime();
  });
};
