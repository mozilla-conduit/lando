# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import boto3
import logging
import tempfile

from flask import current_app

from landoapi.commit_message import format_commit_message
from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.phabricator import collect_accepted_reviewers

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = 's3://{bucket}/{patch_name}'
PATCH_NAME_FORMAT = 'L{landing_id}_D{revision_id}_{diff_id}.patch'


class Patch:
    def __init__(self, landing_id, revision, diff_id):
        """Create a patch instance.

        Args:
            landing_id: Id of the landing in Lando API
            revision: The revision as returned by PhabricatorClient
            diff_id: The id of the diff to be landed
        """
        # check if the diff is related to the revision
        self.validate_diff_assignment(diff_id, revision)

        self.landing_id = landing_id
        self.diff_id = diff_id
        self.revision = revision

    @staticmethod
    def validate_diff_assignment(diff_id, revision):
        """Check if diff is assigned to the revision.

        Args:
            diff_id: The id of the diff to be landed
            revision: The revision as returned by PhabricatorClient

        Raises:
            DiffNotInRevisionException: Request diff ID is not assigned to
                the revision.
        """
        if str(diff_id) not in revision['diffs']:
            raise DiffNotInRevisionException()

    def build(self, phab):
        """Build the patch contents using diff.

        Request diff and revision author from Phabricator API and build the
        patch using the result.

        Returns:
            A string containing a patch in 'hg export' format.

        Raises:
            DiffNotFoundException: PhabricatorClient returned no diff for
                given diff_id.
        """
        raw_diff = phab.get_rawdiff(self.diff_id)
        if not raw_diff:
            raise DiffNotFoundException(self.diff_id)

        # Grab the commit author information which currently only shows up
        # in differential.querydiffs.
        diff = phab.call_conduit('differential.querydiffs', ids=[self.diff_id])
        diff = diff.get(str(self.diff_id)) if diff else {}
        author_name = diff.get('authorName', 'Unknown')
        author_email = diff.get('authorEmail', '')

        # Assume Phabricator is returning valid date responses as "seconds
        # since the Unix Epoch", but cast it to int() just to be sure.  Also
        # assume the Phabricator server is returning that number relative
        # to UTC.
        date_modified = int(self.revision['dateModified'])
        reviewers = phab.get_reviewers(int(self.revision['id']))
        commit_message = format_commit_message(
            self.revision['title'],
            phab.extract_bug_id(self.revision),
            [
                r['fields']['username']
                for r in collect_accepted_reviewers(reviewers)
                if r.get('fields')
            ],
            self.revision['summary'],
            self.revision['uri'],
        )
        return build_patch_for_revision(
            raw_diff, author_name, author_email, commit_message[1],
            date_modified
        )

    def upload(self, phab):
        """Upload the patch to S3 Bucket.

        Build the patch contents and upload to S3.

        Args:
            phab: PhabricatorClient instance
        """
        hgpatch = self.build(phab)

        # Upload patch to S3.
        s3 = boto3.resource(
            's3',
            aws_access_key_id=current_app.config['AWS_ACCESS_KEY'],
            aws_secret_access_key=current_app.config['AWS_SECRET_KEY']
        )
        patch_name = PATCH_NAME_FORMAT.format(
            landing_id=self.landing_id,
            revision_id=self.revision['id'],
            diff_id=self.diff_id
        )
        bucket = current_app.config['PATCH_BUCKET_NAME']
        self.s3_url = PATCH_URL_FORMAT.format(
            bucket=bucket, patch_name=patch_name
        )
        with tempfile.TemporaryFile() as patchfile:
            patchfile.write(hgpatch.encode('utf-8'))
            patchfile.seek(0)
            s3.meta.client.upload_fileobj(patchfile, bucket, patch_name)

        logger.info(
            {
                'patch_url': self.s3_url,
                'msg': 'Patch file uploaded'
            }, 'landing.patch_uploaded'
        )


class DiffNotInRevisionException(Exception):
    """The Diff exists, but it does not belong to the requested revision."""
    pass


class DiffNotFoundException(Exception):
    """Phabricator returned 404 for a given diff id."""

    def __init__(self, diff_id):
        super().__init__()
        self.diff_id = diff_id
