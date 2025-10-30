import json
from textwrap import dedent
from unittest import mock

import pytest
from django.conf import settings

from lando.utils.github import GitHubAPIClient


@pytest.fixture
def github_pr_response() -> str:
    """Return the raw response from a GitHub API request about a PR.

    Data created with

        # curl --user-agent 'shtrom' \
            -H 'Accept: application/vnd.github+json' \
            -H 'X-GitHub-Api-Version: 2022-11-28' \
            https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1 \
            > src/lando/utils/tests/data/github_api_response_pull.json
    """
    json_data_path = (
        settings.BASE_DIR / "utils" / "tests" / "data" / "github_api_response_pull.json"
    )
    with open(json_data_path) as f:
        return f.read()


@pytest.fixture
def github_pr_patch() -> str:
    # curl -LO https://github.com/mozilla-conduit/test-repo/pull/1.patch
    return dedent(
        """
        From ce9fe5d05e5d56a4756019654e3c2b424cd937b2 Mon Sep 17 00:00:00 2001
        From: User <user@example.com>
        Date: Thu, 28 Aug 2025 15:46:57 -0400
        Subject: [PATCH 1/5] second commit

        ---
         test | 1 +
         1 file changed, 1 insertion(+)

        diff --git a/test b/test
        index 89b24ec..7bba8c8 100644
        --- a/test
        +++ b/test
        @@ -1 +1,2 @@
         line 1
        +line 2

        From c27b7d14cb3ddd3ec6a16459156208674b429991 Mon Sep 17 00:00:00 2001
        From: User <user@example.com>
        Date: Tue, 7 Oct 2025 11:24:30 -0400
        Subject: [PATCH 2/5] third commit

        add image
        ---
         favico.ico | Bin 0 -> 4286 bytes
         1 file changed, 0 insertions(+), 0 deletions(-)
         create mode 100644 favico.ico

        diff --git a/favico.ico b/favico.ico
        new file mode 100644
        index 0000000000000000000000000000000000000000..7ae814461d408ed9414e6d76ab8540a3d37d134c
        GIT binary patch
        literal 4286
        zcmc(iF-}}D5Qa?v(Wau_?h$bbDvDeJ7ES>LN}r07B2^kHq}(AXbAfazk!U!<;_qpH
        zn4Qe{c~^^KWb9{;=bIUi{oa<cQ~zeO!vAvrv6RD7%2BO#sGQWw_*m*(P<HBASG^cM
        zoSz@<-pz--ztoFQ`wOa`nM0;mUyt0`a4;M7E?Hu>TI^vBYkL@(%zW7W(&F^YVMnGv
        z8^>-N--z>de!8H3ySg0rAd=A-x_V>LV#E6L`{#o4{PZ}ouRkA;d~BgGPhV`cJvL-)
        z81Pi+i!1%&OD3{o%7!TB54Sf``PxSQdA@|bER1O1qa2Ue_$8lhoAIOkAg`?r#NFzm
        zAF=T%(ue#yeB^CDM!wtqRxD|~oqArEuX7pYT;_Wg`%V034ST?SDIe5kzW@61eQW-Y
        ztmS<!E^QV^VozMGtnFv(vV37Jd*II;K4zt*YZE@~ZSY}dc9S!i-JVTMkk3k{hw-Uu
        z_o~(3gx}IPHRofH#gUj~{!cNo`Dp*Mvk$+O{~4n-4&UE>SsuR!e`Igz{)znL9qr%K
        zD{{+k#g(yo2C^Jz-M?N3&r@el??Ar?{(FPit2F(oOxdA4%5oN__-8};=l#pNsAT%Y
        zrL{Sf$-@+%Hu~0;57rLeO_t^RK6Vk``o3zz+iwc#jckZ?O5WaI(RU(e&N6MEnE3k$
        zz4$bx7ddMyIqY)<-9GM?Pd~E({p>4t;1?AhW3rL4h|7ErTeh@pK$m#1TYDkdb=b0j
        o)}Kr1Tc`Ekx>kQrpYKELi1MOk2WzJGx`%IN-s$&uMf|_=0)^}s4gdfE

        literal 0
        HcmV?d00001


        From 6d13ee6f941eb565909c4dfbae73055ef2247144 Mon Sep 17 00:00:00 2001
        From: User2 <user2@example.com>
        Date: Wed, 8 Oct 2025 17:51:16 +1100
        Subject: [PATCH 3/5] add naughty try task config

        ---
         try_task_config.json | 0
         1 file changed, 0 insertions(+), 0 deletions(-)
         create mode 100644 try_task_config.json

        diff --git a/try_task_config.json b/try_task_config.json
        new file mode 100644
        index 0000000..e69de29

        From 1d9881143c8288d6d230869c8d5e2b26d12862cc Mon Sep 17 00:00:00 2001
        From: User2 <user2@example.com>
        Date: Wed, 8 Oct 2025 18:22:38 +1100
        Subject: [PATCH 4/5] add non-empty b

        ---
         b | 1 +
         1 file changed, 1 insertion(+)
         create mode 100644 b

        diff --git a/b b/b
        new file mode 100644
        index 0000000..e0b3f1b
        --- /dev/null
        +++ b/b
        @@ -0,0 +1 @@
        +bb

        From d1adda9a692e3f362435b4f80ea19aa41c555e69 Mon Sep 17 00:00:00 2001
        From: User2 <user2@example.com>
        Date: Wed, 8 Oct 2025 18:26:29 +1100
        Subject: [PATCH 5/5] add two more files

        ---
         1 | 1 +
         2 | 1 +
         2 files changed, 2 insertions(+)
         create mode 100644 1
         create mode 100644 2

        diff --git a/1 b/1
        new file mode 100644
        index 0000000..d00491f
        --- /dev/null
        +++ b/1
        @@ -0,0 +1 @@
        +1
        diff --git a/2 b/2
        new file mode 100644
        index 0000000..0cfbf08
        --- /dev/null
        +++ b/2
        @@ -0,0 +1 @@
        +2
        """
    ).lstrip()


@pytest.fixture
def github_pr_diff() -> str:
    # curl -LO https://github.com/mozilla-conduit/test-repo/pull/1.diff
    return dedent(
        """
        diff --git a/1 b/1
        new file mode 100644
        index 0000000..d00491f
        --- /dev/null
        +++ b/1
        @@ -0,0 +1 @@
        +1
        diff --git a/2 b/2
        new file mode 100644
        index 0000000..0cfbf08
        --- /dev/null
        +++ b/2
        @@ -0,0 +1 @@
        +2
        diff --git a/b b/b
        new file mode 100644
        index 0000000..e0b3f1b
        --- /dev/null
        +++ b/b
        @@ -0,0 +1 @@
        +bb
        diff --git a/favico.ico b/favico.ico
        new file mode 100644
        index 0000000..7ae8144
        Binary files /dev/null and b/favico.ico differ
        diff --git a/test b/test
        index 89b24ec..7bba8c8 100644
        --- a/test
        +++ b/test
        @@ -1 +1,2 @@
         line 1
        +line 2
        diff --git a/try_task_config.json b/try_task_config.json
        new file mode 100644
        index 0000000..e69de29
        """
    ).lstrip()


def test_api_client_build_pr(
    github_pr_response: str, github_pr_diff: str, github_pr_patch: str
):
    repo = mock.Mock
    repo._github_repo_org = "mozilla-conduit"
    repo.git_repo_name = "test-repo "

    api_client = GitHubAPIClient(repo)

    api_client.get_pull_request = mock.MagicMock()
    api_client.get_pull_request.return_value = json.loads(github_pr_response)

    api_client.get_diff = mock.MagicMock()
    api_client.get_diff.return_value = github_pr_diff

    api_client.get_patch = mock.MagicMock()
    api_client.get_patch.return_value = github_pr_patch

    pr = api_client.build_pull_request(1)

    assert api_client.get_pull_request.call_count == 1
    assert pr.number == 1

    assert pr.diff == github_pr_diff
    assert api_client.get_diff.call_count == 1

    assert pr.patch == github_pr_patch
    assert api_client.get_patch.call_count == 1
