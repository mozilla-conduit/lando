'use strict';

$.fn.treestatus = function() {
    return this.each(function() {
        // Register an on-click handler for each log update edit button.
        $('.log-update-edit').on("click", function () {
            // Toggle the elements from hidden/visible.
            var closest_form = $(this).closest('.log-update-form');

            closest_form.find('.log-update-hidden').toggle();
            closest_form.find('.log-update-visible').toggle();
        });

        // Register an on-click handler for each recent changes edit button.
        $('.recent-changes-edit').on("click", function () {
            // Toggle the elements from hidden/visible.
            var closest_form = $(this).closest('.recent-changes-form');

            closest_form.find('.recent-changes-update-hidden').toggle();
            closest_form.find('.recent-changes-update-visible').toggle();
        });

        // Toggle selected on all trees.
        $('.select-all-trees').on("click", function () {
            var checkboxes = $('.tree-select-checkbox');
            checkboxes.prop('checked', true);
            checkboxes.trigger('change');
        });

        // Toggle un-selected on all trees.
        $('.unselect-all-trees').on("click", function () {
            var checkboxes = $('.tree-select-checkbox');
            checkboxes.prop('checked', false);
            checkboxes.trigger('change');
        });

        // Update the select trees list after update.
        var set_update_trees_list = function () {
            // Clear the current state of the update form tree list.
            var trees_list = $('.update-trees-list')
            trees_list.empty();

            // Get all the checked boxes in the select trees view.
            $('.tree-select-checkbox:checked').each(function () {
                var checkbox = $(this);

                // Add a new `li` element for each selected tree.
                trees_list.append(
                    $('<li></li>').text(checkbox.val())
                );
            });
        };

        // Show the update trees modal when "Update trees" is clicked.
        $('.update-trees-button').on("click", function () {
            $('.update-trees-modal').toggle();
        });

        // Close the update trees modal when the close button is clicked.
        $('.update-trees-modal-close').on("click", function () {
            $('.update-trees-modal').toggle();
        });

        // Add a tree to the list of trees on the update form when checkbox set.
        $('.tree-select-checkbox').on("change", function () {
            set_update_trees_list();

            var checked_trees = $('.tree-select-checkbox:checked');
            // Disaable the "Update trees" button when no trees are selected.
            var is_tree_select_disabled = checked_trees.length > 0 ? false : true;
            $('.update-trees-button').prop('disabled', is_tree_select_disabled);
        });
    });
};
