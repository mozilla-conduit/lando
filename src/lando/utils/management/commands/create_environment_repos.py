from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.utils import IntegrityError

from lando.environments import Environment
from lando.main.models import (
    DONTBUILD,
    SCM_ALLOW_DIRECT_PUSH,
    SCM_CONDUIT,
    SCM_LEVEL_1,
    SCM_LEVEL_3,
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
        #
        # Repos used to test git-hg-sync.
        #
        {
            "name": "unified-first-git",
            "short_name": "unified-first",
            "url": "http://git.test/unified-cinnabar",
            "push_path": "http://lando:password@git.test/unified-cinnabar",
            "default_branch": "first-repo",
            "required_permission": SCM_LEVEL_1,
        },
        {
            "name": "unified-second-git",
            "short_name": "unified-second",
            "url": "http://git.test/unified-cinnabar",
            "push_path": "http://lando:password@git.test/unified-cinnabar",
            "default_branch": "second-repo",
            "required_permission": SCM_LEVEL_1,
        },
        {
            "name": "unified-third-git",
            "short_name": "unified-third",
            "url": "http://git.test/unified-cinnabar",
            "push_path": "http://lando:password@git.test/unified-cinnabar",
            "default_branch": "third-repo",
            "required_permission": SCM_LEVEL_1,
        },
        {
            "name": "unified-test-git",
            "short_name": "unified-test",
            "url": "http://git.test/unified-cinnabar",
            "push_path": "http://lando:password@git.test/unified-cinnabar",
            "default_branch": "test-repo",
            "required_permission": SCM_LEVEL_1,
        },
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
    ],
    Environment.production: [],
}

# RelEng staging repo / branches - used in try pushes
for branch in ["main", "autoland", "beta", "release", "esr115", "esr128"]:
    REPOS[Environment.staging].append(
        {
            "name": f"staging-firefox-{branch}",
            "default_branch": branch,
            "url": "https://github.com/mozilla-releng/staging-firefox.git",
            "push_path": "https://github.com/mozilla-releng/staging-firefox.git",
            "short_name": f"staging-firefox-{branch}",
            "required_permission": SCM_LEVEL_1,
            "automation_enabled": True,
        }
    )

for branch in ["main"]:
    REPOS[Environment.production].append(
        {
            "name": f"firefox-{branch}",
            "default_branch": branch,
            "url": "https://github.com/mozilla-firefox/firefox.git",
            "push_path": "https://github.com/mozilla-firefox/firefox.git",
            "short_name": f"firefox-{branch}",
            "required_permission": (
                SCM_ALLOW_DIRECT_PUSH if branch != "autoland" else SCM_LEVEL_3
            ),
        }
    )


class Command(BaseCommand):
    help = "Create repos based on specified environment."

    def add_arguments(self, parser):  # noqa: ANN001
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
            except ValueError as e:  # when a repo is not reachable
                if environment == Environment.local:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Failed setting up Repo {definition['name']}: {e}, skipping (local only)..."
                        )
                    )
                    # Don't fail on error locally
                    continue
                raise e
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"Created repo {repo.tree} ({repo.id}).")
                )
