import asyncio
import logging
import re

import requests
from django.conf import settings
from simple_github import AppAuth, AppInstallationAuth

logger = logging.getLogger(__name__)

# From RFC-3986.
# XXX: Duplicated from GitSCM to avoid circular import.
URL_USERINFO_RE = re.compile(
    "(?P<userinfo>[-A-Za-z0-9:._~%!$&'*()*+;=]*:[-A-Za-z0-9:._~%!$&'*()*+;=]*@)",
    flags=re.MULTILINE,
)


class GitHubAPI:
    repo_url: str
    repo_owner: str
    repo_name: str
    userinfo: str
    session: requests.Session

    GITHUB_BASE_URL = "https://api.github.com"
    # NOTE: This RE takes care of removing the '.git' suffix, to provide normalised URLs.
    GITHUB_URL_RE = re.compile(
        f"https://{URL_USERINFO_RE.pattern}?github.com/(?P<owner>[-A-Za-z0-9]+)/(?P<repo>[^/]+)(.git)?"
    )

    def __init__(self, repo_url: str):
        self.repo_url = repo_url

        parsed_url = self.parse_github_url(repo_url)

        if parsed_url is None:
            raise ValueError(f"Cannot parse URL as GitHub repo: {repo_url}")

        self.repo_owner = parsed_url["owner"]
        self.repo_name = parsed_url["repo"]
        self.userinfo = parsed_url["userinfo"]

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self._fetch_token()}",
                "User-Agent": settings.HTTP_USER_AGENT,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    @classmethod
    def is_github_url(cls, url: str) -> bool:
        return cls.parse_github_url(url) is not None

    @classmethod
    def parse_github_url(cls, url: str) -> re.Match[str] | None:
        """Parse GitHub data from URL, or return None if not Github."""
        return re.match(cls.GITHUB_URL_RE, url)

    @property
    def authenticated_url(self) -> str:
        """Return an authenticated URL, suitable for use with `git` to push and pull."""
        if self.userinfo:
            # We only fetch a token if no authentication is explicitly specified in
            # the repo_url.
            return self.repo_url

        logger.info(
            f"Obtaining fresh GitHub token for GitHub repo at {self.repo_url}",
        )

        token = self._fetch_token()

        if token:
            return f"https://git:{token}@github.com/{self.repo_owner}/{self.repo_name}"

        # We didn't get a token
        logger.warning(f"Couldn't obtain a token for GitHub repo at {self.repo_url}")
        return self.repo_url

    def _fetch_token(self) -> str | None:
        """Obtain a fresh GitHub token to push to the specified repo.

        This relies on GITHUB_APP_ID and GITHUB_APP_PRIVKEY to be set in the
        environment. Returns None if those are missing.

        The app with ID GITHUB_APP_ID needs to be enabled for the target repo.

        """
        app_id = settings.GITHUB_APP_ID
        private_key = settings.GITHUB_APP_PRIVKEY

        if not app_id or not private_key:
            logger.warning(
                f"Missing GITHUB_APP_ID or GITHUB_APP_PRIVKEY to authenticate against GitHub repo at {self.repo_url}",
            )
            return None

        app_auth = AppAuth(
            app_id,
            private_key,
        )
        session = AppInstallationAuth(
            app_auth, self.repo_owner, repositories=[self.repo_name]
        )
        return asyncio.run(session.get_token())

    def get(self, path: str, *args, **kwargs) -> dict:
        url = f"{self.GITHUB_BASE_URL}/{path}"
        return self.session.get(url, *args, **kwargs)

    def post(self, path: str, *args, **kwargs) -> dict:
        url = f"self.GITHUB_BASE_URL/{path}"
        return self.session.post(url, *args, **kwargs)


class GitHubAPIClient:
    client = None

    def __init__(self, repo_url: str):
        self.client = GitHubAPI(repo_url)
        self.repo = repo_url
        self.repo_base_url = f"repos/{self.client.repo_owner}/{self.client.repo_name}"

    def _get(self, path: str, *args, **kwargs):
        result = self.client.get(path, *args, **kwargs)
        return result.json()

    def list_pull_requests(self) -> list:
        return self._get(f"{self.repo_base_url}/pulls")

    def get_pull_request(self, pull_number: int) -> dict:
        return self._get(f"{self.repo_base_url}/pulls/{pull_number}")
