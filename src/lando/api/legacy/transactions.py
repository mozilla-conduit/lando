"""Functions for working with Phabricator transactions."""

from typing import (
    Iterator,
    NewType,
    Optional,
)

from lando.utils.phabricator import PhabricatorClient

# Type for a Phabricator API Transaction returned by the transaction.search operation.
Transaction = NewType("Transaction", dict)
# Type for list entries in the "comments" list of a transaction returned from the
# Phabricator API transaction.search operation.
Comment = NewType("Comment", dict)


def transaction_search(
    phabricator: PhabricatorClient,
    object_identifier: str,
    transaction_phids: Optional[list[str]] = None,
    limit: int = 100,
) -> Iterator[Transaction]:
    """Yield the Phabricator transactions related to an object.

    See https://phabricator.services.mozilla.com/conduit/method/transaction.search/.

    If the transaction list is larger that one page of API results then the generator
    will call the Phabricator API successive times to fetch the full transaction list.

    Args:
        phabricator: A PhabricatorClient instance.
        object_identifier: An object identifier (PHID or monogram) whose transactions
            we want to fetch.
        transaction_phids: An optional list of specific transactions PHIDs we want to
            find for the given object_identifier.
        limit: Integer keyword, limit the number of records retrieved per API call.
            Default is 100 records.

    Returns:
        Yields individual transactions.
    """
    next_page_start = None

    if transaction_phids:
        constraints = {"phids": transaction_phids}
    else:
        constraints = {}

    while True:
        transactions = phabricator.call_conduit(
            "transaction.search",
            objectIdentifier=object_identifier,
            constraints=constraints,
            limit=limit,
            after=next_page_start,
        )

        yield from PhabricatorClient.expect(transactions, "data")

        next_page_start = PhabricatorClient.expect(transactions, "cursor", "after")

        if next_page_start is None:
            # This was the last page of results.
            return


def get_inline_comments(
    phab: PhabricatorClient, object_identifer: str
) -> Iterator[Transaction]:
    """Returns an iterator of inline comments for the requested object.

    Args:
        phab: A PhabricatorClient instance.
        object_identifer: An object identifier (PHID or monogram) whose inline
            comments we want to fetch.
    """
    return filter(
        lambda transaction: transaction["type"] == "inline",
        transaction_search(phab, object_identifer),
    )
