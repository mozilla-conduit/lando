import json
from typing import Callable
from unittest import mock

import pytest

from lando.utils.github import GitHubAPIClient, PullRequest, PullRequestPatchHelper


@pytest.fixture
def github_api_client(mock_response: Callable) -> Callable:
    def _github_api_client(
        github_pr_response: dict,
        *,
        github_pr_list_response: dict | None = None,
        github_pr_patch: str = "",
        github_pr_diff: str = "",
    ) -> mock.Mock:
        client_mock = mock.Mock()

        client_mock.list_pull_request = mock.Mock(return_value=github_pr_list_response)
        client_mock.get_pull_request = mock.Mock(return_value=github_pr_response)

        def mock_get(url: str) -> str:
            response_map = {
                github_pr_response["patch_url"]: mock_response(text=github_pr_patch),
                github_pr_response["diff_url"]: mock_response(text=github_pr_diff),
            }

            # We don't use 'get' here, as we'd rather it failed loudly if something's
            # missing.
            return response_map[url]

        client_mock.session = mock.Mock()  # GitHubAPI
        client_mock.session.get = mock.Mock(side_effect=mock_get)

        return client_mock

    return _github_api_client


@pytest.fixture
def github_pr_response() -> dict:
    # curl --user-agent 'shtrom' -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28' https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1
    return json.loads(
        '{"url":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1","id":2782816395,"node_id":"PR_kwDONhJ9as6l3miL","html_url":"https://github.com/mozilla-conduit/test-repo/pull/1","diff_url":"https://github.com/mozilla-conduit/test-repo/pull/1.diff","patch_url":"https://github.com/mozilla-conduit/test-repo/pull/1.patch","issue_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/1","number":1,"state":"open","locked":false,"title":"test pull request with multiple commits","user":{"login":"zzuser","id":2043828,"node_id":"MDQ6VXNlcjIwNDM4Mjg=","avatar_url":"https://avatars.githubusercontent.com/u/2043828?v=4","gravatar_id":"","url":"https://api.github.com/users/zzuser","html_url":"https://github.com/zzuser","followers_url":"https://api.github.com/users/zzuser/followers","following_url":"https://api.github.com/users/zzuser/following{/other_user}","gists_url":"https://api.github.com/users/zzuser/gists{/gist_id}","starred_url":"https://api.github.com/users/zzuser/starred{/owner}{/repo}","subscriptions_url":"https://api.github.com/users/zzuser/subscriptions","organizations_url":"https://api.github.com/users/zzuser/orgs","repos_url":"https://api.github.com/users/zzuser/repos","events_url":"https://api.github.com/users/zzuser/events{/privacy}","received_events_url":"https://api.github.com/users/zzuser/received_events","type":"User","user_view_type":"public","site_admin":false},"body":"test description","created_at":"2025-08-28T19:49:55Z","updated_at":"2025-10-08T19:47:21Z","closed_at":null,"merged_at":null,"merge_commit_sha":"09d91ccc46aaa0ee1d2d5324926dbd8725cdbfb3","assignee":null,"assignees":[],"requested_reviewers":[{"login":"shtrom","id":160280,"node_id":"MDQ6VXNlcjE2MDI4MA==","avatar_url":"https://avatars.githubusercontent.com/u/160280?v=4","gravatar_id":"","url":"https://api.github.com/users/shtrom","html_url":"https://github.com/shtrom","followers_url":"https://api.github.com/users/shtrom/followers","following_url":"https://api.github.com/users/shtrom/following{/other_user}","gists_url":"https://api.github.com/users/shtrom/gists{/gist_id}","starred_url":"https://api.github.com/users/shtrom/starred{/owner}{/repo}","subscriptions_url":"https://api.github.com/users/shtrom/subscriptions","organizations_url":"https://api.github.com/users/shtrom/orgs","repos_url":"https://api.github.com/users/shtrom/repos","events_url":"https://api.github.com/users/shtrom/events{/privacy}","received_events_url":"https://api.github.com/users/shtrom/received_events","type":"User","user_view_type":"public","site_admin":false}],"requested_teams":[{"name":"conduit-core","id":2339782,"node_id":"MDQ6VGVhbTIzMzk3ODI=","slug":"conduit-core","description":"Core developers of conduit","privacy":"closed","notification_setting":"notifications_enabled","url":"https://api.github.com/organizations/25333391/team/2339782","html_url":"https://github.com/orgs/mozilla-conduit/teams/conduit-core","members_url":"https://api.github.com/organizations/25333391/team/2339782/members{/member}","repositories_url":"https://api.github.com/organizations/25333391/team/2339782/repos","type":"organization","organization_id":25333391,"permission":"pull","parent":null}],"labels":[],"milestone":null,"draft":true,"commits_url":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1/commits","review_comments_url":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1/comments","review_comment_url":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/comments{/number}","comments_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/1/comments","statuses_url":"https://api.github.com/repos/mozilla-conduit/test-repo/statuses/d1adda9a692e3f362435b4f80ea19aa41c555e69","head":{"label":"mozilla-conduit:branch_b","ref":"branch_b","sha":"d1adda9a692e3f362435b4f80ea19aa41c555e69","user":{"login":"mozilla-conduit","id":25333391,"node_id":"MDEyOk9yZ2FuaXphdGlvbjI1MzMzMzkx","avatar_url":"https://avatars.githubusercontent.com/u/25333391?v=4","gravatar_id":"","url":"https://api.github.com/users/mozilla-conduit","html_url":"https://github.com/mozilla-conduit","followers_url":"https://api.github.com/users/mozilla-conduit/followers","following_url":"https://api.github.com/users/mozilla-conduit/following{/other_user}","gists_url":"https://api.github.com/users/mozilla-conduit/gists{/gist_id}","starred_url":"https://api.github.com/users/mozilla-conduit/starred{/owner}{/repo}","subscriptions_url":"https://api.github.com/users/mozilla-conduit/subscriptions","organizations_url":"https://api.github.com/users/mozilla-conduit/orgs","repos_url":"https://api.github.com/users/mozilla-conduit/repos","events_url":"https://api.github.com/users/mozilla-conduit/events{/privacy}","received_events_url":"https://api.github.com/users/mozilla-conduit/received_events","type":"Organization","user_view_type":"public","site_admin":false},"repo":{"id":907181418,"node_id":"R_kgDONhJ9ag","name":"test-repo","full_name":"mozilla-conduit/test-repo","private":false,"owner":{"login":"mozilla-conduit","id":25333391,"node_id":"MDEyOk9yZ2FuaXphdGlvbjI1MzMzMzkx","avatar_url":"https://avatars.githubusercontent.com/u/25333391?v=4","gravatar_id":"","url":"https://api.github.com/users/mozilla-conduit","html_url":"https://github.com/mozilla-conduit","followers_url":"https://api.github.com/users/mozilla-conduit/followers","following_url":"https://api.github.com/users/mozilla-conduit/following{/other_user}","gists_url":"https://api.github.com/users/mozilla-conduit/gists{/gist_id}","starred_url":"https://api.github.com/users/mozilla-conduit/starred{/owner}{/repo}","subscriptions_url":"https://api.github.com/users/mozilla-conduit/subscriptions","organizations_url":"https://api.github.com/users/mozilla-conduit/orgs","repos_url":"https://api.github.com/users/mozilla-conduit/repos","events_url":"https://api.github.com/users/mozilla-conduit/events{/privacy}","received_events_url":"https://api.github.com/users/mozilla-conduit/received_events","type":"Organization","user_view_type":"public","site_admin":false},"html_url":"https://github.com/mozilla-conduit/test-repo","description":"This is just a test repo.","fork":true,"url":"https://api.github.com/repos/mozilla-conduit/test-repo","forks_url":"https://api.github.com/repos/mozilla-conduit/test-repo/forks","keys_url":"https://api.github.com/repos/mozilla-conduit/test-repo/keys{/key_id}","collaborators_url":"https://api.github.com/repos/mozilla-conduit/test-repo/collaborators{/collaborator}","teams_url":"https://api.github.com/repos/mozilla-conduit/test-repo/teams","hooks_url":"https://api.github.com/repos/mozilla-conduit/test-repo/hooks","issue_events_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/events{/number}","events_url":"https://api.github.com/repos/mozilla-conduit/test-repo/events","assignees_url":"https://api.github.com/repos/mozilla-conduit/test-repo/assignees{/user}","branches_url":"https://api.github.com/repos/mozilla-conduit/test-repo/branches{/branch}","tags_url":"https://api.github.com/repos/mozilla-conduit/test-repo/tags","blobs_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/blobs{/sha}","git_tags_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/tags{/sha}","git_refs_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/refs{/sha}","trees_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/trees{/sha}","statuses_url":"https://api.github.com/repos/mozilla-conduit/test-repo/statuses/{sha}","languages_url":"https://api.github.com/repos/mozilla-conduit/test-repo/languages","stargazers_url":"https://api.github.com/repos/mozilla-conduit/test-repo/stargazers","contributors_url":"https://api.github.com/repos/mozilla-conduit/test-repo/contributors","subscribers_url":"https://api.github.com/repos/mozilla-conduit/test-repo/subscribers","subscription_url":"https://api.github.com/repos/mozilla-conduit/test-repo/subscription","commits_url":"https://api.github.com/repos/mozilla-conduit/test-repo/commits{/sha}","git_commits_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/commits{/sha}","comments_url":"https://api.github.com/repos/mozilla-conduit/test-repo/comments{/number}","issue_comment_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/comments{/number}","contents_url":"https://api.github.com/repos/mozilla-conduit/test-repo/contents/{+path}","compare_url":"https://api.github.com/repos/mozilla-conduit/test-repo/compare/{base}...{head}","merges_url":"https://api.github.com/repos/mozilla-conduit/test-repo/merges","archive_url":"https://api.github.com/repos/mozilla-conduit/test-repo/{archive_format}{/ref}","downloads_url":"https://api.github.com/repos/mozilla-conduit/test-repo/downloads","issues_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues{/number}","pulls_url":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls{/number}","milestones_url":"https://api.github.com/repos/mozilla-conduit/test-repo/milestones{/number}","notifications_url":"https://api.github.com/repos/mozilla-conduit/test-repo/notifications{?since,all,participating}","labels_url":"https://api.github.com/repos/mozilla-conduit/test-repo/labels{/name}","releases_url":"https://api.github.com/repos/mozilla-conduit/test-repo/releases{/id}","deployments_url":"https://api.github.com/repos/mozilla-conduit/test-repo/deployments","created_at":"2024-12-23T02:41:51Z","updated_at":"2025-04-15T02:04:53Z","pushed_at":"2025-10-08T07:26:34Z","git_url":"git://github.com/mozilla-conduit/test-repo.git","ssh_url":"git@github.com:mozilla-conduit/test-repo.git","clone_url":"https://github.com/mozilla-conduit/test-repo.git","svn_url":"https://github.com/mozilla-conduit/test-repo","homepage":null,"size":12,"stargazers_count":0,"watchers_count":0,"language":null,"has_issues":false,"has_projects":false,"has_downloads":true,"has_wiki":false,"has_pages":false,"has_discussions":false,"forks_count":1,"mirror_url":null,"archived":false,"disabled":false,"open_issues_count":1,"license":null,"allow_forking":true,"is_template":false,"web_commit_signoff_required":false,"topics":[],"visibility":"public","forks":1,"open_issues":1,"watchers":0,"default_branch":"main"}},"base":{"label":"mozilla-conduit:branch_a","ref":"branch_a","sha":"61635cec955077dafcf1bc18be380e037368a8da","user":{"login":"mozilla-conduit","id":25333391,"node_id":"MDEyOk9yZ2FuaXphdGlvbjI1MzMzMzkx","avatar_url":"https://avatars.githubusercontent.com/u/25333391?v=4","gravatar_id":"","url":"https://api.github.com/users/mozilla-conduit","html_url":"https://github.com/mozilla-conduit","followers_url":"https://api.github.com/users/mozilla-conduit/followers","following_url":"https://api.github.com/users/mozilla-conduit/following{/other_user}","gists_url":"https://api.github.com/users/mozilla-conduit/gists{/gist_id}","starred_url":"https://api.github.com/users/mozilla-conduit/starred{/owner}{/repo}","subscriptions_url":"https://api.github.com/users/mozilla-conduit/subscriptions","organizations_url":"https://api.github.com/users/mozilla-conduit/orgs","repos_url":"https://api.github.com/users/mozilla-conduit/repos","events_url":"https://api.github.com/users/mozilla-conduit/events{/privacy}","received_events_url":"https://api.github.com/users/mozilla-conduit/received_events","type":"Organization","user_view_type":"public","site_admin":false},"repo":{"id":907181418,"node_id":"R_kgDONhJ9ag","name":"test-repo","full_name":"mozilla-conduit/test-repo","private":false,"owner":{"login":"mozilla-conduit","id":25333391,"node_id":"MDEyOk9yZ2FuaXphdGlvbjI1MzMzMzkx","avatar_url":"https://avatars.githubusercontent.com/u/25333391?v=4","gravatar_id":"","url":"https://api.github.com/users/mozilla-conduit","html_url":"https://github.com/mozilla-conduit","followers_url":"https://api.github.com/users/mozilla-conduit/followers","following_url":"https://api.github.com/users/mozilla-conduit/following{/other_user}","gists_url":"https://api.github.com/users/mozilla-conduit/gists{/gist_id}","starred_url":"https://api.github.com/users/mozilla-conduit/starred{/owner}{/repo}","subscriptions_url":"https://api.github.com/users/mozilla-conduit/subscriptions","organizations_url":"https://api.github.com/users/mozilla-conduit/orgs","repos_url":"https://api.github.com/users/mozilla-conduit/repos","events_url":"https://api.github.com/users/mozilla-conduit/events{/privacy}","received_events_url":"https://api.github.com/users/mozilla-conduit/received_events","type":"Organization","user_view_type":"public","site_admin":false},"html_url":"https://github.com/mozilla-conduit/test-repo","description":"This is just a test repo.","fork":true,"url":"https://api.github.com/repos/mozilla-conduit/test-repo","forks_url":"https://api.github.com/repos/mozilla-conduit/test-repo/forks","keys_url":"https://api.github.com/repos/mozilla-conduit/test-repo/keys{/key_id}","collaborators_url":"https://api.github.com/repos/mozilla-conduit/test-repo/collaborators{/collaborator}","teams_url":"https://api.github.com/repos/mozilla-conduit/test-repo/teams","hooks_url":"https://api.github.com/repos/mozilla-conduit/test-repo/hooks","issue_events_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/events{/number}","events_url":"https://api.github.com/repos/mozilla-conduit/test-repo/events","assignees_url":"https://api.github.com/repos/mozilla-conduit/test-repo/assignees{/user}","branches_url":"https://api.github.com/repos/mozilla-conduit/test-repo/branches{/branch}","tags_url":"https://api.github.com/repos/mozilla-conduit/test-repo/tags","blobs_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/blobs{/sha}","git_tags_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/tags{/sha}","git_refs_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/refs{/sha}","trees_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/trees{/sha}","statuses_url":"https://api.github.com/repos/mozilla-conduit/test-repo/statuses/{sha}","languages_url":"https://api.github.com/repos/mozilla-conduit/test-repo/languages","stargazers_url":"https://api.github.com/repos/mozilla-conduit/test-repo/stargazers","contributors_url":"https://api.github.com/repos/mozilla-conduit/test-repo/contributors","subscribers_url":"https://api.github.com/repos/mozilla-conduit/test-repo/subscribers","subscription_url":"https://api.github.com/repos/mozilla-conduit/test-repo/subscription","commits_url":"https://api.github.com/repos/mozilla-conduit/test-repo/commits{/sha}","git_commits_url":"https://api.github.com/repos/mozilla-conduit/test-repo/git/commits{/sha}","comments_url":"https://api.github.com/repos/mozilla-conduit/test-repo/comments{/number}","issue_comment_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/comments{/number}","contents_url":"https://api.github.com/repos/mozilla-conduit/test-repo/contents/{+path}","compare_url":"https://api.github.com/repos/mozilla-conduit/test-repo/compare/{base}...{head}","merges_url":"https://api.github.com/repos/mozilla-conduit/test-repo/merges","archive_url":"https://api.github.com/repos/mozilla-conduit/test-repo/{archive_format}{/ref}","downloads_url":"https://api.github.com/repos/mozilla-conduit/test-repo/downloads","issues_url":"https://api.github.com/repos/mozilla-conduit/test-repo/issues{/number}","pulls_url":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls{/number}","milestones_url":"https://api.github.com/repos/mozilla-conduit/test-repo/milestones{/number}","notifications_url":"https://api.github.com/repos/mozilla-conduit/test-repo/notifications{?since,all,participating}","labels_url":"https://api.github.com/repos/mozilla-conduit/test-repo/labels{/name}","releases_url":"https://api.github.com/repos/mozilla-conduit/test-repo/releases{/id}","deployments_url":"https://api.github.com/repos/mozilla-conduit/test-repo/deployments","created_at":"2024-12-23T02:41:51Z","updated_at":"2025-04-15T02:04:53Z","pushed_at":"2025-10-08T07:26:34Z","git_url":"git://github.com/mozilla-conduit/test-repo.git","ssh_url":"git@github.com:mozilla-conduit/test-repo.git","clone_url":"https://github.com/mozilla-conduit/test-repo.git","svn_url":"https://github.com/mozilla-conduit/test-repo","homepage":null,"size":12,"stargazers_count":0,"watchers_count":0,"language":null,"has_issues":false,"has_projects":false,"has_downloads":true,"has_wiki":false,"has_pages":false,"has_discussions":false,"forks_count":1,"mirror_url":null,"archived":false,"disabled":false,"open_issues_count":1,"license":null,"allow_forking":true,"is_template":false,"web_commit_signoff_required":false,"topics":[],"visibility":"public","forks":1,"open_issues":1,"watchers":0,"default_branch":"main"}},"_links":{"self":{"href":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1"},"html":{"href":"https://github.com/mozilla-conduit/test-repo/pull/1"},"issue":{"href":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/1"},"comments":{"href":"https://api.github.com/repos/mozilla-conduit/test-repo/issues/1/comments"},"review_comments":{"href":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1/comments"},"review_comment":{"href":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/comments{/number}"},"commits":{"href":"https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1/commits"},"statuses":{"href":"https://api.github.com/repos/mozilla-conduit/test-repo/statuses/d1adda9a692e3f362435b4f80ea19aa41c555e69"}},"author_association":"NONE","auto_merge":null,"active_lock_reason":null,"merged":false,"mergeable":true,"rebaseable":true,"mergeable_state":"clean","merged_by":null,"comments":0,"review_comments":0,"maintainer_can_modify":false,"commits":5,"additions":4,"deletions":0,"changed_files":6}'
    )


@pytest.fixture
def github_pr_patch() -> str:
    # curl -LO https://github.com/mozilla-conduit/test-repo/pull/1.patch
    return """
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
""".lstrip()


@pytest.fixture
def github_pr_diff() -> str:
    # curl -LO https://github.com/mozilla-conduit/test-repo/pull/1.diff
    return """
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
""".lstrip()


def test_api_client_build_pr(
    github_pr_response: dict, github_pr_diff: str, github_pr_patch: str
):
    repo = mock.Mock
    repo._github_repo_org = "mozilla-conduit"
    repo.git_repo_name = "test-repo "

    api_client = GitHubAPIClient(repo)

    api_client.get_pull_request = mock.MagicMock()
    api_client.get_pull_request.return_value = github_pr_response

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


@pytest.fixture
def github_api_client_pr(
    github_api_client: Callable,
    github_pr_response: dict,
    github_pr_patch: str,
    github_pr_diff: str,
) -> mock.Mock:
    return github_api_client(
        github_pr_response,
        github_pr_patch=github_pr_patch,
        github_pr_diff=github_pr_diff,
    )


def test_PullRequestPatchHelper(github_api_client_pr: mock.Mock):
    # This should match the github_pr_response fixture.
    pr_url = "https://api.github.com/repos/mozilla-conduit/test-repo/pulls/1"

    # PR
    # pr = PullRequest(github_api_client_pr, github_api_client_pr.get_pull_request(1))
    pr = github_api_client_pr.build_pull_request(1)

    assert pr.url == pr_url

    # Serialisation
    serialised_pr = pr.serialize()

    assert serialised_pr["url"] == pr_url

    # PatchHelper
    pr_patch_helper = PullRequestPatchHelper(github_api_client_pr, pr)

    assert pr_patch_helper.get_commit_description() == "test description"
    assert pr_patch_helper.get_timestamp() == "1759952841"
    assert pr_patch_helper.parse_author_information() == ("User", "user@example.com")
