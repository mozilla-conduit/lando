import re

# From RFC-3986 [0]:
#
#     userinfo    = *( unreserved / pct-encoded / sub-delims / ":" )
#
#     unreserved  = ALPHA / DIGIT / "-" / "." / "_" / "~"
#     pct-encoded   = "%" HEXDIG HEXDIG
#     sub-delims  = "!" / "$" / "&" / "'" / "(" / ")"
#                 / "*" / "+" / "," / ";" / "=
#
# [0] https://www.rfc-editor.org/rfc/rfc3986
URL_USERINFO_RE = re.compile(
    "(?P<userinfo>[-A-Za-z0-9:._~%!$&'*()*+;=]*:[-A-Za-z0-9:._~%!$&'*()*+;=]*@)",
    flags=re.MULTILINE,
)

# Uplift documentation URL.
UPLIFT_DOCS_URL = (
    "https://wiki.mozilla.org/index.php?title=Release_Management/Requesting_an_Uplift"
)
