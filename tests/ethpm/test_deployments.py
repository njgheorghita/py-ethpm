from eth_utils import to_bytes
import pytest
from web3.eth import Contract

from ethpm import Package
from ethpm.contract import LinkableContract
from ethpm.deployments import Deployments
from ethpm.exceptions import BytecodeLinkingError, ValidationError
from ethpm.utils.deployments import (
    get_linked_deployments,
    normalize_link_dependencies,
    validate_link_dependencies,
)

DEPLOYMENT_DATA = {
    "SafeMathLib": {
        "contract_type": "SafeMathLib",
        "address": "0x8d2c532d7d211816a2807a411f947b211569b68c",
        "transaction": "0xaceef751507a79c2dee6aa0e9d8f759aa24aab081f6dcf6835d792770541cb2b",
        "block": "0x420cb2b2bd634ef42f9082e1ee87a8d4aeeaf506ea5cdeddaa8ff7cbf911810c",
    }
}


@pytest.fixture
def contract_factory(manifest_with_matching_deployment):
    p = Package(manifest_with_matching_deployment)
    return p.get_contract_type("SafeMathLib")


VALID_CONTRACT_TYPES = {"SafeMathLib": contract_factory}
INVALID_CONTRACT_TYPES = {"INVALID": contract_factory}


@pytest.fixture
def deployment(w3):
    return Deployments(DEPLOYMENT_DATA, VALID_CONTRACT_TYPES, w3)


@pytest.fixture
def invalid_deployment(w3):
    return Deployments(DEPLOYMENT_DATA, INVALID_CONTRACT_TYPES, w3)


def test_deployment_implements_getitem(deployment):
    assert deployment["SafeMathLib"] == DEPLOYMENT_DATA["SafeMathLib"]


@pytest.mark.parametrize("name", ("", "-abc", "A=bc", "X" * 257))
def test_deployment_getitem_with_invalid_contract_name_raises_exception(
    name, deployment
):
    with pytest.raises(ValidationError):
        assert deployment[name]


def test_deployment_getitem_without_deployment_reference_raises_exception(deployment):
    with pytest.raises(KeyError):
        deployment["DoesNotExist"]


def test_deployment_getitem_without_contract_type_reference_raises_exception(
    invalid_deployment
):
    with pytest.raises(ValidationError):
        invalid_deployment["SafeMathLib"]


def test_deployment_implements_get_items(deployment):
    expected_items = DEPLOYMENT_DATA.items()
    assert deployment.items() == expected_items


def test_deployment_get_items_with_invalid_contract_names_raises_exception(
    invalid_deployment
):
    with pytest.raises(ValidationError):
        invalid_deployment.items()


def test_deployment_implements_get_values(deployment):
    expected_values = list(DEPLOYMENT_DATA.values())
    assert deployment.values() == expected_values


def test_deployment_get_values_with_invalid_contract_names_raises_exception(
    invalid_deployment
):
    with pytest.raises(ValidationError):
        invalid_deployment.values()


def test_deployment_implements_key_lookup(deployment):
    key = "SafeMathLib" in deployment
    assert key is True


def test_deployment_implements_key_lookup_with_nonexistent_key_raises_exception(
    deployment
):
    key = "invalid" in deployment
    assert key is False


@pytest.mark.parametrize("invalid_name", ("", "-abc", "A=bc", "X" * 257))
def test_get_instance_with_invalid_name_raises_exception(deployment, invalid_name):
    with pytest.raises(ValidationError):
        deployment.get_instance(invalid_name)


def test_get_instance_without_reference_in_deployments_raises_exception(deployment):
    with pytest.raises(KeyError):
        deployment.get_instance("InvalidContract")


def test_get_instance_without_reference_in_contract_factories_raises(
    invalid_deployment
):
    with pytest.raises(ValidationError):
        invalid_deployment.get_instance("SafeMathLib")


def test_deployments_get_instance(manifest_with_matching_deployment, w3):
    manifest, address = manifest_with_matching_deployment
    safe_math_package = Package(manifest, w3)
    deps = safe_math_package.deployments
    safe_math_instance = deps.get_instance("SafeMathLib")
    assert isinstance(safe_math_instance, Contract)
    assert safe_math_instance.address == address
    assert safe_math_instance.bytecode == to_bytes(
        hexstr=safe_math_package.manifest["contract_types"]["SafeMathLib"][
            "deployment_bytecode"
        ]["bytecode"]
    )


def test_deployments_get_contract_instance_with_link_dependency(
    escrow_manifest_with_matching_deployment, w3
):
    manifest, link_ref = escrow_manifest_with_matching_deployment
    EscrowPackage = Package(manifest, w3)
    deployments = EscrowPackage.deployments
    escrow_deployment = deployments.get_deployment_instance("Escrow")
    assert isinstance(escrow_deployment, LinkableContract)


def test_get_linked_deployments(escrow_manifest_with_matching_deployment):
    all_deployments = list(
        escrow_manifest_with_matching_deployment[0]["deployments"].values()
    )[0]
    escrow_deployment = all_deployments["Escrow"]
    actual_linked_deployments = get_linked_deployments(all_deployments)
    assert actual_linked_deployments == {"Escrow": escrow_deployment}


@pytest.mark.parametrize(
    "deployments",
    (
        (
            {
                "Escrow": {
                    "contract_type": "Escrow",
                    "address": "0x8c1968deB27251A3f1F4508df32dA4dfD1b7b57f",
                    "transaction": "0xc60e32c63abf34579390ef65d83cc5eb52225de38c3eeca2e5afa961d71c16d0",  # noqa: E501
                    "block": "0x4d1a618802bb87752d95db453dddeea622820424a2f836bedf8769a67ee276b8",
                    "runtime_bytecode": {
                        "link_dependencies": [
                            {
                                "offsets": [301, 495],
                                "type": "reference",
                                "value": "Escrow",
                            }
                        ]
                    },
                }
            },
        )
    ),
)
def test_get_linked_deployments_raises_exception_with_self_reference(deployments):
    with pytest.raises(BytecodeLinkingError):
        get_linked_deployments(deployments)


@pytest.mark.parametrize(
    "link_data,expected",
    (
        (
            [
                {"offsets": [1], "type": "reference", "value": "123"},
                {"offsets": [2, 3], "type": "literal", "value": "abc"},
            ],
            ((1, "reference", "123"), (2, "literal", "abc"), (3, "literal", "abc")),
        ),
        (
            [{"offsets": [1, 2, 3], "type": "literal", "value": "123"}],
            ((1, "literal", "123"), (2, "literal", "123"), (3, "literal", "123")),
        ),
    ),
)
def test_normalize_link_dependencies(link_data, expected):
    link_deps = normalize_link_dependencies(link_data)
    assert link_deps == expected


@pytest.mark.parametrize(
    "link_deps,bytecode",
    (
        (((1, b"abc"),), b"xabc"),
        (((1, b"a"), (5, b"xx"), (15, b"1")), b"0a000xx000000001"),
    ),
)
def test_validate_link_dependencies(link_deps, bytecode):
    result = validate_link_dependencies(link_deps, bytecode)
    assert result is None


@pytest.mark.parametrize(
    "link_deps,bytecode",
    (
        (((0, b"abc"),), b"xabc"),
        (((2, b"abc"),), b"xabc"),
        (((8, b"abc"),), b"xabc"),
        (((1, b"a"), (5, b"xxx"), (15, b"1")), b"0a000xx000000001"),
    ),
)
def test_validate_link_dependencies_invalidates(link_deps, bytecode):
    with pytest.raises(ValidationError):
        validate_link_dependencies(link_deps, bytecode)
