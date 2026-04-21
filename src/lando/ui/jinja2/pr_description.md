{# Helpers for generating warnings and blockers #}
{% macro _warning(content) %}:warning: {{ content }}{% endmacro %}
{% macro _blocker(content) %}:no_entry_sign: {{ content }}{% endmacro %}
{% macro _column(content) %}|{{ content }}|{% endmacro %}
{% macro _header() %}|---------|{% endmacro %}
{% macro _table(title, entries, macro) %}
{{ _column(title) }}
{{ _header() }}
{% for entry in entries %}
{{ macro(entry) }}
{% endfor %}
{% endmacro %}

{% block upper %}
Lando: [link]({{ lando_url }})
{% if bugs %}Bugzilla: {% for bug in bugs %}[bug {{ bug.0 }}]({{ bug.1 }}){% endfor %}{% endif %}

{% if not warnings and not blockers %}
:white_check_mark: All Lando checks passed
{% endif %}

{% if warnings %}
{{ _table("Warnings", warnings, _warning) }}
{% endif %}

{% if blockers %}
{{ _table("Blockers", blockers, _blocker) }}
{% endif %}

{% endblock %}

<!--/ DO NOT REMOVE THE LINE BELOW /-->
{{ special_delimiter }}

{% block lower %}
{{ body|e }}
{% endblock %}
