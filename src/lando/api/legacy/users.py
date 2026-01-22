from lando.utils.phabricator import PhabricatorClient, result_list_to_phid_dict


def user_search(
    phabricator: PhabricatorClient, user_phids: list[str]
) -> dict[str, dict]:
    """Return a dictionary mapping phid to user information from a user.search.

    Args:
        phabricator: A PhabricatorClient instance.
        user_phids: A list of user phids to search.
    """
    if not user_phids:
        return {}

    users = phabricator.call_conduit("user.search", constraints={"phids": user_phids})
    return result_list_to_phid_dict(phabricator.expect(users, "data"))
