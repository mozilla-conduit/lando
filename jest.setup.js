// The legacy JavaScript files assume jQuery is available as the global `$`
// (loaded via a `<script>` tag in production). Shim it here so files using
// the jQuery-plugin pattern (`$.fn.foo = ...`) can be `require`d in tests.
const jquery = require("jquery");
global.jQuery = jquery;
global.$ = jquery;
