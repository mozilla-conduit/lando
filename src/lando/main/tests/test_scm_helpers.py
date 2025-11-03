import io
from typing import Callable

import pytest

from lando.main.scm.consts import SCM_TYPE_GIT
from lando.main.scm.helpers import (
    GitPatchHelper,
    HgPatchHelper,
    build_patch_for_revision,
)

GIT_DIFF_FROM_REVISION = r"""diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {
        printf("hello, world!\n");
+       printf("sure am glad I'm using Mercurial!\n");
        return 0;
 }
"""

GIT_DIFF_CRLF = """diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)\r
 {\r
        printf("hello, world!\\n");\r
+       printf("sure am glad I'm using Mercurial!\\n");\r
        return 0;\r
 }\r
"""

COMMIT_MESSAGE = """\
Express great joy at existence of Mercurial

Make sure multiple line breaks are kept:



Using console to print out the messages.
"""

HG_PATCH = r"""# HG changeset patch
# User Joe User <joe@example.com>
# Date 1496239141 +0000
# Diff Start Line 12
Express great joy at existence of Mercurial

Make sure multiple line breaks are kept:



Using console to print out the messages.

diff --git a/hello.c b/hello.c
--- a/hello.c   Fri Aug 26 01:21:28 2005 -0700
+++ b/hello.c   Mon May 05 01:20:46 2008 +0200
@@ -12,5 +12,6 @@
 int main(int argc, char **argv)
 {
        printf("hello, world!\n");
+       printf("sure am glad I'm using Mercurial!\n");
        return 0;
 }
"""

#
# GIT_PATCH CONSTANT AND COMPONENTS
#

GIT_PATCH_HEADER = r"""
From 0f5a3c99e12c1e9b0e81bed245fe537961f89e57 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
""".lstrip()

GIT_PATCH_COMMIT_DESC = """
errors: add a maintenance-mode specific title to serverside
 error handlers (Bug 1724769)

Adds a conditional to the Lando-API exception handlers that
shows a maintenance-mode specific title when a 503 error is
returned from Lando. This should inform users that Lando is
unavailable at the moment and is not broken.
""".strip()

# Patches in email-formatted messages will flow long lines. When parsing the patch, the
# commit message gets unflowed. We keep the unflowed version here, too, for comparison
# purposes.
GIT_PATCH_COMMIT_DESC_UNFLOWED = """
errors: add a maintenance-mode specific title to serverside error handlers (Bug 1724769)

Adds a conditional to the Lando-API exception handlers that
shows a maintenance-mode specific title when a 503 error is
returned from Lando. This should inform users that Lando is
unavailable at the moment and is not broken.
""".strip()

GIT_PATCH_STATS = """
---
 landoui/errorhandlers.py | 8 +++++++-
 1 file changed, 7 insertions(+), 1 deletion(-)

""".lstrip()

GIT_PATCH_DIFF = """
diff --git a/landoui/errorhandlers.py b/landoui/errorhandlers.py
index f56ba1c..33391ea 100644
--- a/landoui/errorhandlers.py
+++ b/landoui/errorhandlers.py
@@ -122,10 +122,16 @@ def landoapi_exception(e):
     sentry.captureException()
     logger.exception("Uncaught communication exception with Lando API.")

+    if e.status_code == 503:
+        # Show a maintenance-mode specific title if we get a 503.
+        title = "Lando is undergoing maintenance and is temporarily unavailable"
+    else:
+        title = "Lando API returned an unexpected error"
+
     return (
         render_template(
             "errorhandlers/default_error.html",
-            title="Lando API returned an unexpected error",
+            title=title,
             message=str(e),
         ),
         500,
""".lstrip()

GIT_PATCH = f"{GIT_PATCH_HEADER}Subject: [PATCH] {GIT_PATCH_COMMIT_DESC}\n{GIT_PATCH_STATS}\n{GIT_PATCH_DIFF}-- 2.31.1\n"

#
# END GIT_PATCH CONSTANT AND COMPONENTS
#

GIT_DIFF_UTF8 = """\
diff --git a/testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html b/testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html
new file mode 100644
--- /dev/null
+++ b/testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html
@@ -0,0 +1,31 @@
+<!DOCTYPE html>
+<html class="reftest-wait">
+<meta charset="utf-8">
+<title>Dynamic changes with textContent and dir=auto</title>
+<link rel="match" href="dir-auto-dynamic-simple-ref.html">
+<div>Test for elements with dir="auto" whose content changes between directional and neutral</div>
+<div dir="auto" id="from_ltr_to_ltr">abc</div>
+<div dir="auto" id="from_ltr_to_rtl">abc</div>
+<div dir="auto" id="from_ltr_to_neutral">abc</div>
+<div dir="auto" id="from_rtl_to_ltr">אבג</div>
+<div dir="auto" id="from_rtl_to_rtl">אבג</div>
+<div dir="auto" id="from_rtl_to_neutral">אבג</div>
+<div dir="auto" id="from_neutral_to_ltr">123</div>
+<div dir="auto" id="from_neutral_to_rtl">123</div>
+<div dir="auto" id="from_neutral_to_neutral">123</div>
+<script>
+function changeContent() {
+  var directionalTexts = {ltr:"xyz", rtl:"ابج", neutral:"456"};
+
+  for (var dirFrom in directionalTexts) {
+    for (var dirTo in directionalTexts) {
+      var element = document.getElementById("from_" + dirFrom +
+                                            "_to_" + dirTo);
+      element.textContent = directionalTexts[dirTo];
+    }
+  }
+  document.documentElement.removeAttribute("class");
+}
+
+document.addEventListener("TestRendered", changeContent);
+</script>
"""

GIT_FORMATPATCH_UTF8 = f"""\
From 71ce7889eaa24616632a455636598d8f5c60b765 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 21 Feb 2024 10:20:49 +0000
Subject: [PATCH] Bug 1874040 - Move 1103348-1.html to WPT, and expand it.
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: 8bit

 r=smaug

---
 .../dir-auto-dynamic-simple-textContent.html  | 31 ++++++++++++++++
 1 files changed, 31 insertions(+), 0 deletions(-)
 create mode 100644 testing/web-platform/tests/html/dom/elements/global-attributes/dir-auto-dynamic-simple-textContent.html
{GIT_DIFF_UTF8}--
2.46.1
"""

GIT_DIFF_BINARY = b"""\
diff --git a/mobile/android/android-components/components/lib/publicsuffixlist/src/main/assets/publicsuffixes b/mobile/android/android-components/components/lib/publicsuffixlist/src/main/assets/publicsuffixes
index 6fbd7cfa64d3a..7b7d3f1f381b3 100644
--- a/mobile/android/android-components/components/lib/publicsuffixlist/src/main/assets/publicsuffixes
+++ b/mobile/android/android-components/components/lib/publicsuffixlist/src/main/assets/publicsuffixes
@@ -1,1 +1,1 @@
-\x00\x01\xa3j*.0emm.com
+\x00\x02\x13\x7f*.001.test.code-builder-stg.platform.salesforce.com
"""

GIT_FORMATPATCH_BINARY = (
    b"""\
From cbe35d45ef715ea5cdf4067fb6b090f0904a41cf Mon Sep 17 00:00:00 2001
From: Ryan VanderMeulen <rvandermeulen@mozilla.com>
Date: Tue, 19 Aug 2025 07:16:40 +1000
Subject: [PATCH] Bug 1944726 - Update Android public suffix list.
 r=#android-reviewers

Differential Revision: https://phabricator.services.mozilla.com/D260093
---
 .../src/main/assets/publicsuffixes            | 2933 +++++++++++------
 .../publicsuffixlist/PublicSuffixListTest.kt  |    2 +-
 2 files changed, 1888 insertions(+), 1047 deletions(-)

"""
    + GIT_DIFF_BINARY
    + b"""\
-- \n2.50.1
"""
)

GIT_DIFF = """diff --git a/landoui/errorhandlers.py b/landoui/errorhandlers.py
index f56ba1c..33391ea 100644
--- a/landoui/errorhandlers.py
+++ b/landoui/errorhandlers.py
@@ -122,10 +122,16 @@ def landoapi_exception(e):
     sentry.captureException()
     logger.exception("Uncaught communication exception with Lando API.")

+    if e.status_code == 503:
+        # Show a maintenance-mode specific title if we get a 503.
+        title = "Lando is undergoing maintenance and is temporarily unavailable"
+    else:
+        title = "Lando API returned an unexpected error"
+
     return (
         render_template(
             "errorhandlers/default_error.html",
-            title="Lando API returned an unexpected error",
+            title=title,
             message=str(e),
         ),
         500,
"""

GIT_PATCH_EMPTY = """\
From 0f5a3c99e12c1e9b0e81bed245fe537961f89e57 Mon Sep 17 00:00:00 2001
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
Subject: [PATCH] errors: add a maintenance-mode specific title to serverside
 error handlers (Bug 1724769)

Adds a conditional to the Lando-API exception handlers that
shows a maintenance-mode specific title when a 503 error is
returned from Lando. This should inform users that Lando is
unavailable at the moment and is not broken.
--
2.31.1
"""


def test_build_patch():
    patch = build_patch_for_revision(
        GIT_DIFF_FROM_REVISION,
        "Joe User",
        "joe@example.com",
        COMMIT_MESSAGE,
        "1496239141",
    )

    assert patch == HG_PATCH


@pytest.mark.parametrize(
    "line, expected",
    [
        ("diff --git a/file b/file", True),
        ("diff a/file b/file", True),
        ("diff -r 23280edf8655 autoland/autoland/patch_helper.py", True),
        ("cheese", False),
        ("diff", False),
        ("diff ", False),
        ("diff file", False),
    ],
)
def test_patchhelper_is_diff_line(line: str, expected: str):
    assert bool(HgPatchHelper.is_diff_line(line)) is expected


def test_patchhelper_vanilla_export():
    patch = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_header("Date") == "1523427125 -28800"
    assert patch.get_header("Node ID") == "3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07"
    assert patch.get_header("User") == "byron jones <glob@mozilla.com>"
    assert patch.get_header("Parent") == "46c36c18528fe2cc780d5206ed80ae8e37d3545d"
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_start_line():
    patch = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
# Diff Start Line 10
WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_header("Diff Start Line") == "10"
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_no_header():
    patch = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# Date 1523427125 -28800
WIP transplant and diff-start-line

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_header("User") is None
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_no_start_line():
    patch = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
WIP transplant and diff-start-line

diff --git a/bad b/bad
@@ -0,0 +0,0 @@
blah

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_commit_description() == "WIP transplant and diff-start-line"


def test_patchhelper_diff_injection_start_line():
    patch = HgPatchHelper.from_string_io(
        io.StringIO(
            """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
# Diff Start Line 14
WIP transplant and diff-start-line

diff --git a/bad b/bad
@@ -0,0 +0,0 @@
blah

diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
        )
    )
    assert patch.get_commit_description() == (
        "WIP transplant and diff-start-line\n"
        "\n"
        "diff --git a/bad b/bad\n"
        "@@ -0,0 +0,0 @@\n"
        "blah"
    )


def test_patchhelper_write_start_line():
    header = """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
# Diff Start Line 10
""".strip()
    commit_desc = """
WIP transplant and diff-start-line
""".strip()
    diff = """
diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
    patch_text = "%s\n%s\n\n%s" % (header, commit_desc, diff)
    patch = HgPatchHelper.from_string_io(io.StringIO(patch_text))

    buf = io.StringIO("")
    patch.write_commit_description(buf)
    assert buf.getvalue() == commit_desc

    buf = io.StringIO("")
    patch.write_diff(buf)
    assert buf.getvalue() == diff

    buf = io.StringIO("")
    patch.write(buf)
    assert buf.getvalue() == patch_text


def test_patchhelper_write_no_start_line():
    header = """
# HG changeset patch
# User byron jones <glob@mozilla.com>
# Date 1523427125 -28800
#      Wed Apr 11 14:12:05 2018 +0800
# Node ID 3379ea3cea34ecebdcb2cf7fb9f7845861ea8f07
# Parent  46c36c18528fe2cc780d5206ed80ae8e37d3545d
""".strip()
    commit_desc = """
WIP transplant and diff-start-line
""".strip()
    diff = """
diff --git a/autoland/autoland/transplant.py b/autoland/autoland/transplant.py
--- a/autoland/autoland/transplant.py
+++ b/autoland/autoland/transplant.py
@@ -318,24 +318,58 @@ class PatchTransplant(Transplant):
# instead of passing the url to 'hg import' to make
...
""".strip()
    patch = HgPatchHelper.from_string_io(
        io.StringIO(f"{header}\n{commit_desc}\n\n{diff}")
    )

    buf = io.StringIO("")
    patch.write_commit_description(buf)
    assert buf.getvalue() == commit_desc

    assert patch.get_diff() == diff

    buf = io.StringIO("")
    patch.write_diff(buf)
    assert buf.getvalue() == diff


def test_git_formatpatch_helper_parse():
    patch = GitPatchHelper.from_string_io(io.StringIO(GIT_PATCH))
    assert (
        patch.get_header("From") == "Connor Sheehan <sheehan@mozilla.com>"
    ), "`From` header should contain author information."
    assert (
        patch.get_header("Date") == "Wed, 06 Jul 2022 16:36:09 -0400"
    ), "`Date` header should contain raw date info."
    assert patch.get_header("Subject") == (
        "[PATCH] errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)"
    ), "`Subject` header should contain raw subject header."
    assert patch.get_commit_description() == (
        "errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)\n\n"
        "Adds a conditional to the Lando-API exception handlers that\n"
        "shows a maintenance-mode specific title when a 503 error is\n"
        "returned from Lando. This should inform users that Lando is\n"
        "unavailable at the moment and is not broken."
    ), "`commit_description()` should return full commit message."
    assert patch.get_diff() == GIT_DIFF, "`get_diff()` should return the full diff."


def test_git_formatpatch_helper_write():
    patch = GitPatchHelper.from_string_io(io.StringIO(GIT_PATCH))

    buf = io.StringIO("")
    patch.write_commit_description(buf)
    assert buf.getvalue() == GIT_PATCH_COMMIT_DESC_UNFLOWED

    buf = io.StringIO("")
    patch.write_diff(buf)
    assert buf.getvalue() == GIT_PATCH_DIFF

    buf = io.StringIO("")
    patch.write(buf)
    assert buf.getvalue() == GIT_PATCH


def test_git_formatpatch_helper_empty_commit():
    patch = GitPatchHelper.from_string_io(io.StringIO(GIT_PATCH_EMPTY))
    assert (
        patch.get_header("From") == "Connor Sheehan <sheehan@mozilla.com>"
    ), "`From` header should contain author information."
    assert (
        patch.get_header("Date") == "Wed, 06 Jul 2022 16:36:09 -0400"
    ), "`Date` header should contain raw date info."
    assert patch.get_header("Subject") == (
        "[PATCH] errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)"
    ), "`Subject` header should contain raw subject header."
    assert patch.get_commit_description() == (
        "errors: add a maintenance-mode specific title to serverside error handlers "
        "(Bug 1724769)\n\n"
        "Adds a conditional to the Lando-API exception handlers that\n"
        "shows a maintenance-mode specific title when a 503 error is\n"
        "returned from Lando. This should inform users that Lando is\n"
        "unavailable at the moment and is not broken."
    ), "`commit_description()` should return full commit message."
    assert patch.get_diff() == "", "`get_diff()` should return an empty string."


def test_git_formatpatch_helper_utf8():
    helper = GitPatchHelper.from_string_io(io.StringIO(GIT_FORMATPATCH_UTF8))

    assert (
        helper.get_diff() == GIT_DIFF_UTF8
    ), "`get_diff()` should return unescaped unicode and match the original patch."


def test_git_formatpatch_helper_binary():
    helper = GitPatchHelper.from_bytes_io(io.BytesIO(GIT_FORMATPATCH_BINARY))

    assert (
        helper.get_diff_bytes() == GIT_DIFF_BINARY
    ), "`get_diff_bytes()` did not return the original binary contents."


def test_preserves_diff_crlf():
    hg_patch = build_patch_for_revision(
        GIT_DIFF_CRLF,
        "Joe User",
        "joe@example.com",
        COMMIT_MESSAGE,
        "1496239141",
    )

    hg_helper = HgPatchHelper.from_string_io(io.StringIO(hg_patch))

    assert (
        hg_helper.get_diff() == "\n" + GIT_DIFF_CRLF
    ), "`get_diff()` should preserve CRLF."

    git_helper = GitPatchHelper.from_string_io(
        io.StringIO(
            f"""\
From: Connor Sheehan <sheehan@mozilla.com>
Date: Wed, 6 Jul 2022 16:36:09 -0400
Subject: {COMMIT_MESSAGE}
---
{GIT_DIFF_CRLF}--
2.47.1
"""
        )
    )

    assert git_helper.get_diff() == GIT_DIFF_CRLF, "`get_diff()` should preserve CRLF."


def test_strip_git_version_info_lines():
    lines = [
        "blah",
        "blah",
        "--",
        "git version info",
        "",
        "",
    ]

    assert GitPatchHelper.strip_git_version_info_lines(lines) == [
        "blah",
        "blah",
    ]
