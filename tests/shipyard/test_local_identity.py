from collections.abc import Mapping

import pytest

from aifde.shipyard.identity import (
    LocalOwnerIdentityProvider,
    Principal,
    UnauthorizedError,
)


def test_local_owner_provider_resolves_only_configured_owner() -> None:
    provider = LocalOwnerIdentityProvider("alice")

    assert provider.resolve({"X-Shipyard-Identity": "alice"}) == provider.principal
    assert provider.principal == Principal(
        subject="alice",
        kind="human",
        roles=frozenset({"workspace-owner", "release-owner"}),
    )


@pytest.mark.parametrize(
    "context",
    [{}, {"X-Shipyard-Identity": "bob"}, {"X-Shipyard-Identity": ""}],
)
def test_local_owner_provider_rejects_missing_or_other_subject(
    context: Mapping[str, str],
) -> None:
    provider = LocalOwnerIdentityProvider("alice")

    with pytest.raises(UnauthorizedError):
        provider.resolve(context)


def test_local_owner_provider_rejects_claimed_roles_or_kind() -> None:
    provider = LocalOwnerIdentityProvider("alice")

    with pytest.raises(UnauthorizedError):
        provider.verify(
            Principal(
                subject="alice",
                kind="agent",
                roles=frozenset({"workspace-owner"}),
            )
        )
