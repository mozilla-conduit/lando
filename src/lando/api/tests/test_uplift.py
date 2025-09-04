import pytest
from django.contrib.messages import get_messages
from django.urls import reverse
from packaging.version import (
    Version,
)

from lando.api.legacy.stacks import (
    build_stack_graph,
)
from lando.api.legacy.uplift import (
    add_original_revision_line_if_needed,
    create_uplift_bug_update_payload,
    get_latest_non_commit_diff,
    get_revisions_without_bugs,
    parse_milestone_version,
    strip_depends_on_from_commit_message,
)
from lando.main.models.uplift import (
    LowMediumHighChoices,
    UpliftAssessment,
    UpliftRevision,
    YesNoChoices,
    YesNoUnknownChoices,
)
from lando.ui.legacy.forms import (
    UpliftAssessmentEditForm,
)
from lando.utils.phabricator import (
    PhabricatorClient,
)

MILESTONE_TEST_CONTENTS_1 = """
# Holds the current milestone.
# Should be in the format of
#
#    x.x.x
#    x.x.x.x
#    x.x.x+
#
# Referenced by build/moz.configure/init.configure.
# Hopefully I'll be able to automate replacement of *all*
# hardcoded milestones in the tree from these two files.
#--------------------------------------------------------

84.0a1
"""

MILESTONE_TEST_CONTENTS_2 = """
# Holds the current milestone.
# Should be in the format of
#
#    x.x.x
#    x.x.x.x
#    x.x.x+
#
# Referenced by build/moz.configure/init.configure.
# Hopefully I'll be able to automate replacement of *all*
# hardcoded milestones in the tree from these two files.
#--------------------------------------------------------

105.0
"""


def test_parse_milestone_version():
    assert parse_milestone_version(MILESTONE_TEST_CONTENTS_1) == Version(
        "84.0a1"
    ), "Test milestone file 1 should have 84 as major milestone version."

    assert parse_milestone_version(MILESTONE_TEST_CONTENTS_2) == Version(
        "105.0"
    ), "Test milestone file 2 should have 84 as major milestone version."

    bad_milestone_contents = "blahblahblah"
    with pytest.raises(ValueError, match=bad_milestone_contents):
        parse_milestone_version(bad_milestone_contents)


DEPENDS_ON_MESSAGE = """
bug 123: testing r?sheehan

Something something Depends on D1234

Differential Revision: http://phab.test/D234

Depends on D567
""".strip()


def test_strip_depends_on_from_commit_message():
    assert strip_depends_on_from_commit_message(DEPENDS_ON_MESSAGE) == (
        "bug 123: testing r?sheehan\n"
        "\n"
        "Something something Depends on D1234\n"
        "\n"
        "Differential Revision: http://phab.test/D234\n"
    ), "`Depends on` line should be stripped from commit message."


@pytest.mark.xfail(strict=True)
def test_uplift_creation(
    db,
    monkeypatch,
    phabdouble,
    client,
    mock_permissions,
    mock_repo_config,
    release_management_project,
    needs_data_classification_project,
):
    def _call_conduit(client, method, **kwargs):
        if method == "differential.revision.edit":
            # Load transactions
            transactions = kwargs.get("transactions")
            assert transactions is not None
            transactions = {t["type"]: t["value"] for t in transactions}

            # Check the state of the added transactions is valid for the first uplift.
            if transactions["update"] == "PHID-DIFF-1":
                # Check the expected transactions
                expected = {
                    "update": "PHID-DIFF-1",
                    "title": "Add feature XXX",
                    "summary": (
                        "some really complex stuff\n"
                        "\n"
                        "Original Revision: http://phabricator.test/D1"
                    ),
                    "bugzilla.bug-id": "",
                    "reviewers.add": ["blocking(PHID-PROJ-0)"],
                }
                for key in expected:
                    assert (
                        transactions[key] == expected[key]
                    ), f"key does not match: {key}"

            depends_on = []
            if "parents.set" in transactions:
                depends_on.append({"phid": transactions["parents.set"][0]})

            # Create a new revision
            new_rev = phabdouble.revision(
                title=transactions["title"],
                summary=transactions["summary"],
                depends_on=depends_on,
            )
            return {
                "object": {"id": new_rev["id"], "phid": new_rev["phid"]},
                "transactions": [
                    {"phid": "PHID-XACT-DREV-fakeplaceholder"} for t in transactions
                ],
            }

        else:
            # Every other request fall back in phabdouble
            return phabdouble.call_conduit(method, **kwargs)

    # Intercept the revision creation to avoid transactions support in phabdouble
    monkeypatch.setattr(PhabricatorClient, "call_conduit", _call_conduit)

    diff = phabdouble.diff()
    revision = phabdouble.revision(
        title="Add feature XXX",
        summary=(
            "some really complex stuff\n"
            "\n"
            "Differential Revision: http://phabricator.test/D1"
        ),
        diff=diff,
    )
    repo_mc = phabdouble.repo()
    user = phabdouble.user(username="JohnDoe")
    repo_uplift = phabdouble.repo(name="mozilla-uplift")

    payload = {
        "landing_path": [
            {"revision_id": f"D{revision['id']}", "diff_id": diff["id"]},
        ],
        "repository": repo_mc["shortName"],
    }

    # No auth
    response = client.post("/uplift", json=payload)
    assert response.json["title"] == "X-Phabricator-API-Key Required"
    assert response.status_code == 401

    # API key but no auth0
    headers = {"X-Phabricator-API-Key": user["apiKey"]}
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json["title"] == "Authorization Header Required"

    # Invalid repository (not uplift)
    response = client.post(
        "/uplift", json=payload, headers=headers, permissions=mock_permissions
    )
    assert response.status_code == 400
    assert (
        response.json["title"]
        == "Repository mozilla-central is not an uplift repository."
    )

    # Only one revision at first
    assert len(phabdouble._revisions) == 1

    # Valid uplift repository
    payload["repository"] = repo_uplift["shortName"]
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json == {
        "PHID-DREV-1": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 2,
            "diff_phid": "PHID-DIFF-1",
            "revision_id": 2,
            "revision_phid": "PHID-DREV-1",
            "url": "http://phabricator.test/D2",
        },
        "tip_differential": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 2,
            "diff_phid": "PHID-DIFF-1",
            "revision_id": 2,
            "revision_phid": "PHID-DREV-1",
            "url": "http://phabricator.test/D2",
        },
    }

    # Now we have a new uplift revision on Phabricator
    assert len(phabdouble._revisions) == 2
    new_rev = phabdouble._revisions[-1]
    assert new_rev["title"] == "Add feature XXX"
    assert (
        new_rev["summary"]
        == "some really complex stuff\n\nOriginal Revision: http://phabricator.test/D1"
    )

    # Add some more revisions to test uplifting a stack.
    diff2 = phabdouble.diff()
    rev2 = phabdouble.revision(
        title="bug 1: xxx r?reviewer",
        summary=("summary info.\n\nDifferential Revision: http://phabricator.test/D3"),
        diff=diff2,
    )
    diff3 = phabdouble.diff()
    rev3 = phabdouble.revision(
        title="bug 1: yyy r?reviewer",
        summary=("summary two.\n\nDifferential Revision: http://phabricator.test/D4"),
        depends_on=[rev2],
        diff=diff3,
    )
    diff4 = phabdouble.diff()
    rev4 = phabdouble.revision(
        title="bug 1: yyy r?reviewer",
        summary=("summary two.\n\nDifferential Revision: http://phabricator.test/D4"),
        depends_on=[rev3],
        diff=diff4,
    )

    # Send an uplift request for a stack.
    payload["landing_path"] = [
        {"revision_id": f"D{rev2['id']}", "diff_id": diff2["id"]},
        {"revision_id": f"D{rev3['id']}", "diff_id": diff3["id"]},
        {"revision_id": f"D{rev4['id']}", "diff_id": diff4["id"]},
    ]
    response = client.post("/uplift", json=payload, headers=headers)
    assert response.status_code == 201, "Response should have status code 201."
    assert len(response.json) == 4, "API call should have created 3 revisions."
    assert response.json == {
        "PHID-DREV-5": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 7,
            "diff_phid": "PHID-DIFF-6",
            "revision_id": 6,
            "revision_phid": "PHID-DREV-5",
            "url": "http://phabricator.test/D6",
        },
        "PHID-DREV-6": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 9,
            "diff_phid": "PHID-DIFF-8",
            "revision_id": 7,
            "revision_phid": "PHID-DREV-6",
            "url": "http://phabricator.test/D7",
        },
        "PHID-DREV-7": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 11,
            "diff_phid": "PHID-DIFF-10",
            "revision_id": 8,
            "revision_phid": "PHID-DREV-7",
            "url": "http://phabricator.test/D8",
        },
        "tip_differential": {
            "mode": "uplift",
            "repository": "mozilla-uplift",
            "diff_id": 11,
            "diff_phid": "PHID-DIFF-10",
            "revision_id": 8,
            "revision_phid": "PHID-DREV-7",
            "url": "http://phabricator.test/D8",
        },
    }, "Response JSON does not match expected."

    # Check that parent-child relationships are preserved.
    phab = phabdouble.get_phabricator_client()
    last_phid = response.json["tip_differential"]["revision_phid"]
    _nodes, edges = build_stack_graph(phab, last_phid)

    assert edges == {
        ("PHID-DREV-7", "PHID-DREV-6"),
        ("PHID-DREV-6", "PHID-DREV-5"),
    }, "Uplift does not preserve parent/child relationships."
    # We still have the same revision
    assert len(phabdouble._revisions) == 1
    new_rev = phabdouble._revisions[0]
    assert new_rev["title"] == "no bug: my test revision title"


def test_create_uplift_bug_update_payload():
    bug = {
        "cf_status_firefox100": "---",
        "id": 123,
        "keywords": [],
        "whiteboard": "[checkin-needed-beta]",
    }
    payload = create_uplift_bug_update_payload(
        bug, "beta", 100, "cf_status_firefox{milestone}"
    )

    assert payload["ids"] == [123], "Passed bug ID should be present in the payload."
    assert (
        payload["whiteboard"] == ""
    ), "checkin-needed flag should be removed from whiteboard."
    assert (
        payload["cf_status_firefox100"] == "fixed"
    ), "Custom tracking flag should be set to `fixed`."

    bug = {
        "cf_status_firefox100": "---",
        "id": 123,
        "keywords": ["leave-open"],
        "whiteboard": "[checkin-needed-beta]",
    }
    payload = create_uplift_bug_update_payload(
        bug, "beta", 100, "cf_status_firefox{milestone}"
    )

    assert (
        "cf_status_firefox100" not in payload
    ), "Status should not have been set with `leave-open` keyword on bug."


def test_add_original_revision_line_if_needed():
    uri = "http://phabricator.test/D123"

    summary_no_original = "Bug 123: test summary r?sheehan"
    summary_with_original = (
        "Bug 123: test summary r?sheehan\n"
        "\n"
        "Original Revision: http://phabricator.test/D123"
    )

    assert (
        add_original_revision_line_if_needed(summary_no_original, uri)
        == summary_with_original
    ), "Passing summary without `Original Revision` should return with line added."

    assert (
        add_original_revision_line_if_needed(summary_with_original, uri)
        == summary_with_original
    ), "Passing summary with `Original Revision` should return the input."


def test_get_revisions_without_bugs(phabdouble):
    phab = phabdouble.get_phabricator_client()

    rev1 = phabdouble.revision(bug_id=123)
    revs = phabdouble.differential_revision_search(
        constraints={"phids": [rev1["phid"]]},
    )
    revisions = phab.expect(revs, "data")

    assert (
        get_revisions_without_bugs(phab, revisions) == set()
    ), "Empty set should be returned if all revisions have bugs."

    rev2 = phabdouble.revision()
    revs = phabdouble.differential_revision_search(
        constraints={"phids": [rev1["phid"], rev2["phid"]]},
    )
    revisions = phab.expect(revs, "data")

    assert get_revisions_without_bugs(phab, revisions) == {
        rev2["id"]
    }, "Revision without associated bug should be returned."


def test_get_latest_non_commit_diff():
    test_data = [
        {"creationMethod": "commit", "id": 3},
        {"creationMethod": "moz-phab-hg", "id": 1},
        {"creationMethod": "commit", "id": 4},
        {"creationMethod": "moz-phab-hg", "id": 2},
        {"creationMethod": "commit", "id": 5},
    ]

    diff = get_latest_non_commit_diff(test_data)

    assert (
        diff["id"] == 2
    ), "Returned diff should have the highest diff ID without `commit`."
    assert (
        diff["creationMethod"] != "commit"
    ), "Diffs with a `creationMethod` of `commit` should be skipped."


@pytest.mark.django_db
def test_to_conduit_json_transforms_fields(user):
    instance = UpliftAssessment.objects.create(
        user=user,
        user_impact="Impact",
        covered_by_testing=YesNoUnknownChoices.YES,
        fix_verified_in_nightly=YesNoChoices.NO,
        needs_manual_qe_testing=YesNoChoices.YES,
        qe_testing_reproduction_steps="Steps",
        risk_associated_with_patch=LowMediumHighChoices.HIGH,
        risk_level_explanation="Explanation",
        string_changes="Changes",
        is_android_affected=YesNoUnknownChoices.UNKNOWN,
    )

    conduit_dict = instance.to_conduit_json()
    assert isinstance(conduit_dict, dict), "`to_conduit_json` should return a `dict`."
    assert (
        conduit_dict["User impact if declined"] == "Impact"
    ), "`user_impact` field should not be transformed."
    assert (
        conduit_dict["Code covered by automated testing"] is True
    ), "`No` should be converted to `False`."
    assert (
        conduit_dict["Fix verified in Nightly"] is False
    ), "`No` should be converted to `False`."
    assert (
        conduit_dict["Needs manual QE test"] is True
    ), "`Yes` should be converted to `True`."
    assert (
        conduit_dict["Is Android affected?"] is False
    ), "`Unknown` should be converted to `False`."
    assert (
        conduit_dict["Risk associated with taking this patch"] == "high"
    ), "Text choice should be converted to `str`."

    conduit_str = instance.to_conduit_json_str()

    assert (
        conduit_str
        == '{"User impact if declined": "Impact", "Code covered by automated testing": true, "Fix verified in Nightly": false, "Needs manual QE test": true, "Steps to reproduce for manual QE testing": "Steps", "Risk associated with taking this patch": "high", "Explanation of risk level": "Explanation", "String changes made/needed": "Changes", "Is Android affected?": false}'
    ), "`to_conduit_json_str` should return dict as a string."


CREATE_FORM_DATA = {
    "revision_id": "D1234",
    "user_impact": "Initial impact description.",
    "covered_by_testing": "yes",
    "fix_verified_in_nightly": "no",
    "needs_manual_qe_testing": "no",
    "qe_testing_reproduction_steps": "",
    "risk_associated_with_patch": "low",
    "risk_level_explanation": "Low risk because it's well-tested.",
    "string_changes": "No changes.",
    "is_android_affected": "no",
}

UPDATED_FORM_DATA = {
    "revision_id": "D1234",
    "user_impact": "Updated impact after more testing.",
    "covered_by_testing": "no",
    "fix_verified_in_nightly": "yes",
    "needs_manual_qe_testing": "yes",
    "qe_testing_reproduction_steps": "Steps go here.",
    "risk_associated_with_patch": "medium",
    "risk_level_explanation": "Medium risk due to timing.",
    "string_changes": "Yes, minor updates.",
    "is_android_affected": "yes",
}


@pytest.mark.django_db
def test_patch_assessment_creates_and_updates(authenticated_client, user, phabdouble):
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    url = reverse("uplift-assessment-page")

    form = UpliftAssessmentEditForm(data=CREATE_FORM_DATA)
    assert form.is_valid(), f"Form was invalid: {form.errors.as_json()}"

    # Submit the form for an revision.
    response = authenticated_client.post(
        url, data=CREATE_FORM_DATA, HTTP_REFERER="/D1234"
    )
    assert response.status_code == 302, "Patch should redirect back to referrer."

    # Check that a new response was created
    responses = UpliftAssessment.objects.all()
    assert responses.count() == 1, "Updating a form should result in a single form."

    response_obj = responses.first()
    assert (
        response_obj.user_impact == CREATE_FORM_DATA["user_impact"]
    ), "`user_impact` field should match the initial value."

    revision = UpliftRevision.objects.get()
    assert revision.revision_id == 1234, "Revision ID should match initial value."
    assert (
        revision.assessment == response_obj
    ), "Response object for the revision should match the queried model."

    # Submit the form for a revision which already has a completed form.
    response = authenticated_client.post(
        url, data=UPDATED_FORM_DATA, HTTP_REFERER="/D1234"
    )
    assert response.status_code == 302, "Patch should redirect back to referrer."

    # Check that a new response was created
    responses = UpliftAssessment.objects.all()
    assert responses.count() == 1, "Updating a form should result in a single form."

    updated_response_obj = responses.first()
    assert (
        updated_response_obj.user_impact == UPDATED_FORM_DATA["user_impact"]
    ), "User impact should be updated to a new value."

    revision.refresh_from_db()
    assert (
        revision.assessment == updated_response_obj
    ), "Revision should point to the new response."


@pytest.mark.django_db
def test_patch_assessment_form_invalid(authenticated_client, user, phabdouble):
    phabdouble.user(api_key=user.profile.phabricator_api_key)

    url = reverse("uplift-assessment-page")

    # Form is invalid because required fields are missing or invalid
    invalid_data = {
        "revision_id": "D1234",
        # Required field left empty.
        "user_impact": "",
        "covered_by_testing": "yes",
        "fix_verified_in_nightly": "no",
        "needs_manual_qe_testing": "yes",
        # Required as `needs_manual_qe_testing` is `yes`.
        "qe_testing_reproduction_steps": "",
        "risk_associated_with_patch": "low",
        "risk_level_explanation": "Low risk because it's well-tested.",
        "string_changes": "No changes.",
        "is_android_affected": "no",
    }

    response = authenticated_client.post(url, data=invalid_data, HTTP_REFERER="/D1234")

    assert response.status_code == 302, "Submission should redirect on error."
    assert (
        UpliftAssessment.objects.count() == 0
    ), "Assessment should not be saved on error."
    assert (
        UpliftRevision.objects.count() == 0
    ), "Assessment should not be associated with a revision."

    messages = [str(message) for message in get_messages(response.wsgi_request)]
    for bad_field in ("qe_testing_reproduction_steps", "user_impact"):
        assert any(
            bad_field in message for message in messages
        ), f"Validation message not sent for `{bad_field}`."
