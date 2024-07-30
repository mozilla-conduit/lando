from enum import Enum


class RepoTypeEnum(Enum):
    GIT = "git"
    HG = "hg"

    @classmethod
    def choices(cls):
        return [(key.value, key.name) for key in cls]


# DONTBUILD flag and help text.
DONTBUILD = (
    "DONTBUILD",
    (
        "Should be used only for trivial changes (typo, comment changes,"
        " documentation changes, etc.) where the risk of introducing a"
        " new bug is close to none."
    ),
)

REPO_CONFIG = {
    # '<ENV>': {
    #     '<phabricator-short-name>': {...}
    # }
    "default": {},
    "localdev": {
        "test-repo": {
            "name": "test-repo",
            "url": "http://hg.test/test-repo",
            "access_group_permission": "scm_level_1",
            "product_details_url": "http://product-details.test/1.0/firefox_versions.json",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "first-repo": {
            "name": "first-repo",
            "url": "http://hg.test/first-repo",
            "push_path": "ssh://autoland.hg//repos/first-repo",
            "access_group_permission": "scm_level_1",
            "commit_flags": [DONTBUILD],
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "second-repo": {
            "name": "second-repo",
            "url": "http://hg.test/second-repo",
            "access_group_permission": "scm_level_1",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "third-repo": {
            "name": "third-repo",
            "url": "http://hg.test/third-repo",
            "access_group_permission": "scm_level_1",
            "push_path": "ssh://autoland.hg//repos/third-repo",
            "pull_path": "http://hg.test/third-repo",
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        # "git-test-repo": {
        #    "name": "git-test-repo",
        #    "url": "https://github.com/zzzeid/test-repo.git",
        #    "access_group_permission": "scm_conduit",
        #    "repo_type_enum": RepoTypeEnum.GIT,
        # },
    },
    "devsvcdev": {
        "test-repo": {
            "name": "test-repo",
            "url": "https://hg.mozilla.org/conduit-testing/test-repo",
            "access_group_permission": "scm_conduit",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "m-c": {
            "name": "m-c",
            "url": "https://hg.mozilla.org/conduit-testing/m-c",
            "access_group_permission": "scm_conduit",
            "commit_flags": [DONTBUILD],
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "product_details_url": "https://raw.githubusercontent.com/mozilla-conduit/suite/main/docker/product-details/1.0/firefox_versions.json",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "vct": {
            "name": "vct",
            "url": "https://hg.mozilla.org/conduit-testing/vct",
            "access_group_permission": "scm_conduit",
            "push_bookmark": "@",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        # Use real `try` for testing since `try` is a testing environment anyway.
        "try": {
            "name": "try",
            "url": "https://hg.mozilla.org/try",
            "push_path": "ssh://hg.mozilla.org/try",
            "pull_path": "https://hg.mozilla.org/mozilla-unified",
            "access_group_permission": "scm_level_1",
            "short_name": "try",
            "is_phabricator_repo": False,
            "force_push": True,
            "repo_type_enum": RepoTypeEnum.HG,
        },
    },
    "devsvcstage": {
        "test-repo-clone": {
            "name": "test-repo-clone",
            "url": "https://hg.mozilla.org/conduit-testing/test-repo-clone",
            "access_group_permission": "scm_conduit",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        # Use real `try` for testing since `try` is a testing environment anyway.
        "try": {
            "name": "try",
            "url": "https://hg.mozilla.org/try",
            "push_path": "ssh://hg.mozilla.org/try",
            "pull_path": "https://hg.mozilla.org/mozilla-unified",
            "access_group_permission": "scm_level_1",
            "short_name": "try",
            "is_phabricator_repo": False,
            "force_push": True,
            "repo_type_enum": RepoTypeEnum.HG,
        },
    },
    "devsvcprod": {
        "phabricator-qa-stage": {
            "name": "phabricator-qa-stage",
            "url": "https://hg.mozilla.org/automation/phabricator-qa-stage",
            "access_group_permission": "scm_level_3",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "version-control-tools": {
            "name": "version-control-tools",
            "url": "https://hg.mozilla.org/hgcustom/version-control-tools",
            "access_group_permission": "scm_versioncontrol",
            "push_bookmark": "@",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "build-tools": {
            "name": "build-tools",
            "url": "https://hg.mozilla.org/build/tools/",
            "access_group_permission": "scm_level_3",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "ci-admin": {
            "name": "ci-admin",
            "url": "https://hg.mozilla.org/ci/ci-admin",
            "access_group_permission": "scm_firefoxci",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "ci-configuration": {
            "name": "ci-configuration",
            "url": "https://hg.mozilla.org/ci/ci-configuration",
            "access_group_permission": "scm_firefoxci",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "fluent-migration": {
            "name": "fluent-migration",
            "url": "https://hg.mozilla.org/l10n/fluent-migration",
            "access_group_permission": "scm_l10n_infra",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "mozilla-central": {
            "name": "autoland",
            "url": "https://hg.mozilla.org/integration/autoland",
            "access_group_permission": "scm_level_3",
            "short_name": "mozilla-central",
            "commit_flags": [DONTBUILD],
            "product_details_url": "https://product-details.mozilla.org/1.0/firefox_versions.json",
            "autoformat_enabled": True,
            "repo_type_enum": RepoTypeEnum.HG,
        },
        # Try uses `mozilla-unified` as the `pull_path` as using try
        # proper is exceptionally slow. `mozilla-unified` includes both
        # autoland and central and is the most likely to contain the passed
        # base commit.
        "try": {
            "name": "try",
            "url": "https://hg.mozilla.org/try",
            "push_path": "ssh://hg.mozilla.org/try",
            "pull_path": "https://hg.mozilla.org/mozilla-unified",
            "access_group_permission": "scm_level_1",
            "short_name": "try",
            "is_phabricator_repo": False,
            "force_push": True,
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "comm-central": {
            "name": "comm-central",
            "url": "https://hg.mozilla.org/comm-central",
            "access_group_permission": "scm_level_3",
            "commit_flags": [DONTBUILD],
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "nspr": {
            "name": "nspr",
            "url": "https://hg.mozilla.org/projects/nspr",
            "access_group_permission": "scm_nss",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "taskgraph": {
            "name": "taskgraph",
            "url": "https://hg.mozilla.org/ci/taskgraph",
            "access_group_permission": "scm_level_3",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "nss": {
            "name": "nss",
            "url": "https://hg.mozilla.org/projects/nss",
            "access_group_permission": "scm_nss",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "pine": {
            "name": "pine",
            "url": "https://hg.mozilla.org/projects/pine",
            "access_group_permission": "scm_level_3",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "elm": {
            "name": "elm",
            "url": "https://hg.mozilla.org/projects/elm",
            "access_group_permission": "scm_level_3",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "mozilla-build": {
            "name": "mozilla-build",
            "url": "https://hg.mozilla.org/mozilla-build",
            "access_group_permission": "scm_level_3",
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "beta": {
            "name": "mozilla-beta",
            "short_name": "beta",
            "url": "https://hg.mozilla.org/releases/mozilla-beta",
            "access_group_permission": "scm_allow_direct_push",
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "commit_flags": [DONTBUILD],
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "release": {
            "name": "mozilla-release",
            "short_name": "release",
            "url": "https://hg.mozilla.org/releases/mozilla-release",
            "access_group_permission": "scm_allow_direct_push",
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "commit_flags": [DONTBUILD],
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "esr102": {
            "name": "mozilla-esr102",
            "short_name": "esr102",
            "url": "https://hg.mozilla.org/releases/mozilla-esr102",
            "access_group_permission": "scm_allow_direct_push",
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox_esr{milestone}",
            "commit_flags": [DONTBUILD],
            "repo_type_enum": RepoTypeEnum.HG,
        },
        "esr115": {
            "name": "mozilla-esr115",
            "short_name": "esr115",
            "url": "https://hg.mozilla.org/releases/mozilla-esr115",
            "access_group_permission": "scm_allow_direct_push",
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox_esr{milestone}",
            "commit_flags": [DONTBUILD],
            "repo_type_enum": RepoTypeEnum.HG,
        },
    },
}
