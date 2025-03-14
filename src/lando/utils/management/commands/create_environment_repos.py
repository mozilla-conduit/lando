from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.utils import IntegrityError

from lando.environments import Environment
from lando.main.models import (
    DONTBUILD,
    SCM_ALLOW_DIRECT_PUSH,
    SCM_CONDUIT,
    SCM_FIREFOXCI,
    SCM_L10N_INFRA,
    SCM_LEVEL_1,
    SCM_LEVEL_3,
    SCM_NSS,
    SCM_VERSIONCONTROL,
    Repo,
)
from lando.main.scm import GitSCM

ENVIRONMENTS = [e for e in Environment if not e.is_test]

# These repos are copied from the legacy repo "subsystem".
REPOS = {
    Environment.local: [
        {
            "name": "git-repo",
            "url": "https://github.com/mozilla-conduit/test-repo.git",
            "required_permission": SCM_LEVEL_1,
            "scm_type": GitSCM.scm_type(),
        },
        {
            "name": "test-repo-git",
            "url": "http://git.test/test-repo",
            "pull_path": "http://git.test/test-repo",
            "push_path": "http://lando:password@git.test/test-repo",
            "required_permission": SCM_LEVEL_1,
            "scm_type": GitSCM.scm_type(),
        },
        {
            "name": "test-repo",
            "url": "http://hg.test/test-repo",
            "required_permission": SCM_LEVEL_1,
            "product_details_url": "http://product-details.test/1.0/firefox_versions.json",
        },
        {
            "name": "first-repo",
            "url": "http://hg.test/first-repo",
            "push_path": "ssh://autoland.hg//repos/first-repo",
            "required_permission": SCM_LEVEL_1,
            "commit_flags": [DONTBUILD],
        },
        {
            "name": "second-repo",
            "url": "http://hg.test/second-repo",
            "required_permission": SCM_LEVEL_1,
        },
        {
            "name": "third-repo",
            "url": "http://hg.test/third-repo",
            "required_permission": SCM_LEVEL_1,
            "push_path": "ssh://autoland.hg//repos/third-repo",
            "pull_path": "http://hg.test/third-repo",
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
        },
        # # Approval is required for the uplift dev repo
        # {
        #     "name": "uplift-target",
        #     "url": "http://hg.test",  # TODO: fix this? URL is probably incorrect.
        #     "required_permission": SCM_LEVEL_1,
        #     "approval_required": True,
        #     "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
        # },
    ],
    Environment.development: [
        {
            "name": "test-repo",
            "url": "https://hg.mozilla.org/conduit-testing/test-repo",
            "required_permission": SCM_CONDUIT,
        },
        {
            "name": "m-c",
            "url": "https://hg.mozilla.org/conduit-testing/m-c",
            "required_permission": SCM_CONDUIT,
            "commit_flags": [DONTBUILD],
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "product_details_url": "https://raw.githubusercontent.com/mozilla-conduit"
            "/suite/main/docker/product-details/1.0/firefox_versions.json",
        },
        {
            "name": "large-repo",
            "url": "https://hg.mozilla.org/conduit-testing/m-c",
            "required_permission": SCM_CONDUIT,
            "commit_flags": [DONTBUILD],
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "product_details_url": "https://raw.githubusercontent.com/mozilla-conduit"
            "/suite/main/docker/product-details/1.0/firefox_versions.json",
        },
        {
            "name": "vct",
            "url": "https://hg.mozilla.org/conduit-testing/vct",
            "required_permission": SCM_CONDUIT,
            "push_target": "@",
        },
        # Use real `try` for testing since `try` is a testing environment anyway.
        {
            "name": "try",
            "url": "https://hg.mozilla.org/try",
            "push_path": "ssh://hg.mozilla.org/try",
            "pull_path": "https://hg.mozilla.org/mozilla-unified",
            "required_permission": SCM_LEVEL_1,
            "short_name": "try",
            "is_phabricator_repo": False,
            "force_push": True,
        },
    ],
    Environment.staging: [
        {
            "name": "test-repo-clone",
            "url": "https://hg.mozilla.org/conduit-testing/test-repo-clone",
            "required_permission": SCM_CONDUIT,
        },
        # Use real `try` for testing since `try` is a testing environment anyway.
        {
            "name": "try",
            "url": "https://hg.mozilla.org/try",
            "push_path": "ssh://hg.mozilla.org/try",
            "pull_path": "https://hg.mozilla.org/mozilla-unified",
            "required_permission": SCM_LEVEL_1,
            "short_name": "try",
            "is_phabricator_repo": False,
            "force_push": True,
        },
    ],
    Environment.production: [
        {
            "name": "phabricator-qa-stage",
            "url": "https://hg.mozilla.org/automation/phabricator-qa-stage",
            "required_permission": SCM_LEVEL_3,
        },
        {
            "name": "version-control-tools",
            "url": "https://hg.mozilla.org/hgcustom/version-control-tools",
            "required_permission": SCM_VERSIONCONTROL,
            "push_target": "@",
        },
        {
            "name": "build-tools",
            "url": "https://hg.mozilla.org/build/tools/",
            "required_permission": SCM_LEVEL_3,
        },
        {
            "name": "ci-admin",
            "url": "https://hg.mozilla.org/ci/ci-admin",
            "required_permission": SCM_FIREFOXCI,
        },
        {
            "name": "ci-configuration",
            "url": "https://hg.mozilla.org/ci/ci-configuration",
            "required_permission": SCM_FIREFOXCI,
        },
        {
            "name": "fluent-migration",
            "url": "https://hg.mozilla.org/l10n/fluent-migration",
            "required_permission": SCM_L10N_INFRA,
        },
        {
            "name": "autoland",
            "url": "https://hg.mozilla.org/integration/autoland",
            "required_permission": SCM_LEVEL_3,
            "short_name": "mozilla-central",
            "commit_flags": [DONTBUILD],
            "product_details_url": "https://product-details.mozilla.org"
            "/1.0/firefox_versions.json",
            "autoformat_enabled": True,
        },
        # Try uses `mozilla-unified` as the `pull_path` as using try
        # proper is exceptionally slow. `mozilla-unified` includes both
        # autoland and central and is the most likely to contain the passed
        # base commit.
        {
            "name": "try",
            "url": "https://hg.mozilla.org/try",
            "push_path": "ssh://hg.mozilla.org/try",
            "pull_path": "https://hg.mozilla.org/mozilla-unified",
            "required_permission": SCM_LEVEL_1,
            "short_name": "try",
            "is_phabricator_repo": False,
            "force_push": True,
        },
        {
            "name": "comm-central",
            "url": "https://hg.mozilla.org/comm-central",
            "required_permission": SCM_LEVEL_3,
            "commit_flags": [DONTBUILD],
        },
        {
            "name": "nspr",
            "url": "https://hg.mozilla.org/projects/nspr",
            "required_permission": SCM_NSS,
        },
        {
            "name": "taskgraph",
            "url": "https://hg.mozilla.org/ci/taskgraph",
            "required_permission": SCM_LEVEL_3,
        },
        {
            "name": "nss",
            "url": "https://hg.mozilla.org/projects/nss",
            "required_permission": SCM_NSS,
        },
        {
            "name": "pine",
            "url": "https://hg.mozilla.org/projects/pine",
            "required_permission": SCM_LEVEL_3,
        },
        {
            "name": "elm",
            "url": "https://hg.mozilla.org/projects/elm",
            "required_permission": SCM_LEVEL_3,
        },
        {
            "name": "mozilla-build",
            "url": "https://hg.mozilla.org/mozilla-build",
            "required_permission": SCM_LEVEL_3,
        },
        {
            "name": "mozilla-beta",
            "short_name": "beta",
            "url": "https://hg.mozilla.org/releases/mozilla-beta",
            "required_permission": SCM_ALLOW_DIRECT_PUSH,
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "commit_flags": [DONTBUILD],
        },
        {
            "name": "mozilla-release",
            "short_name": "release",
            "url": "https://hg.mozilla.org/releases/mozilla-release",
            "required_permission": SCM_ALLOW_DIRECT_PUSH,
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox{milestone}",
            "commit_flags": [DONTBUILD],
        },
        {
            "name": "mozilla-esr102",
            "short_name": "esr102",
            "url": "https://hg.mozilla.org/releases/mozilla-esr102",
            "required_permission": SCM_ALLOW_DIRECT_PUSH,
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox_esr{milestone}",
            "commit_flags": [DONTBUILD],
        },
        {
            "name": "mozilla-esr115",
            "short_name": "esr115",
            "url": "https://hg.mozilla.org/releases/mozilla-esr115",
            "required_permission": SCM_ALLOW_DIRECT_PUSH,
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox_esr{milestone}",
            "commit_flags": [DONTBUILD],
        },
        {
            "name": "mozilla-esr128",
            "short_name": "esr128",
            "url": "https://hg.mozilla.org/releases/mozilla-esr128",
            "required_permission": SCM_ALLOW_DIRECT_PUSH,
            "approval_required": True,
            "milestone_tracking_flag_template": "cf_status_firefox_esr{milestone}",
            "commit_flags": [DONTBUILD],
        },
    ],
}


class Command(BaseCommand):
    help = "Create repos based on specified environment."

    def add_arguments(self, parser):
        parser.add_argument(
            "environment",
            help=f"Enter one of {', '.join(ENVIRONMENTS)}",
        )

        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="Force creation of repos even if request does not match current environment",
        )

    def handle(self, *args, **options):
        environment = options["environment"]
        if environment not in ENVIRONMENTS:
            raise CommandError(
                f"Environment must be one of: {', '.join(ENVIRONMENTS)}. "
                f'"{environment}" was provided.'
            )

        environment = Environment(environment)

        if environment != settings.ENVIRONMENT and not options["force"]:
            raise CommandError(
                f"Current environment {settings.ENVIRONMENT} does not match requested "
                f"environment ({environment}). Pass --force to do this anyway."
            )

        repo_definitions = REPOS[environment]
        for definition in repo_definitions:
            try:
                repo = Repo.objects.create(**definition)
            except IntegrityError as e:
                self.stderr.write(str(e))
                self.stdout.write(
                    self.style.WARNING(
                        f"Repo {definition['name']} already exists or could not be added, skipping."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"Created repo {repo.tree} ({repo.id}).")
                )
