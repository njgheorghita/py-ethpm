import functools
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cytoolz
from eth_utils import add_0x_prefix, to_dict, to_list
from eth_utils.toolz import assoc, assoc_in, curry, pipe
from web3 import Web3

from ethpm import Package
from ethpm.backends.ipfs import BaseIPFSBackend
from ethpm.exceptions import ManifestBuildingError, ValidationError
from ethpm.typing import Manifest
from ethpm.utils.manifest_validation import validate_manifest_against_schema


def build(obj, *fns):
    """
    Wrapper function to pipe manifest through build functions.
    Does not validate the manifest by default.
    """
    return pipe(obj, *fns)


#
# Required Fields
#


@curry
def package_name(name: str, manifest: Manifest) -> Manifest:
    """
    Return a copy of manifest with `name` set to "package_name".
    """
    return assoc(manifest, "package_name", name)


@curry
def manifest_version(manifest_version: str, manifest: Manifest) -> Manifest:
    """
    Return a copy of manifest with `manifest_version` set to "manifest_version".
    """
    return assoc(manifest, "manifest_version", manifest_version)


@curry
def version(version: str, manifest: Manifest) -> Manifest:
    """
    Return a copy of manifest with `version` set to "version".
    """
    return assoc(manifest, "version", version)


#
# Meta
#


def authors(*author_list):
    """
    Return a copy of manifest with a list of author posargs set to "meta": {"authors": author_list}
    """
    return _authors(author_list)


@curry
@functools.wraps(authors)
def _authors(authors: set, manifest: Manifest) -> Manifest:
    return assoc_in(manifest, ("meta", "authors"), list(authors))


@curry
def license(license: str, manifest: Manifest) -> Manifest:
    """
    Return a copy of manifest with `license` set to "meta": {"license": `license`}
    """
    return assoc_in(manifest, ("meta", "license"), license)


@curry
def description(description: str, manifest: Manifest) -> Manifest:
    """
    Return a copy of manifest with `description` set to "meta": {"descriptions": `description`}
    """
    return assoc_in(manifest, ("meta", "description"), description)


def keywords(*keyword_list):
    """
    Return a copy of manifest with a list of keyword posargs set to
    "meta": {"keywords": keyword_list}
    """
    return _keywords(keyword_list)


@curry
@functools.wraps(keywords)
def _keywords(keywords: set, manifest: Manifest) -> Manifest:
    return assoc_in(manifest, ("meta", "keywords"), list(keywords))


def links(**link_dict):
    """
    Return a copy of manifest with a dict of link kwargs set to "meta": {"links": link_dict}
    """
    return _links(link_dict)


@curry
def _links(link_dict: Dict[str, str], manifest: Manifest) -> Manifest:
    return assoc_in(manifest, ("meta", "links"), link_dict)


#
# Sources
#


def get_names_and_paths(compiler_output: Dict[str, Any]) -> Dict[str, str]:
    """
    Return a mapping of contract name to relative path as defined in compiler output.
    """
    return {
        contract_name: path
        for path in compiler_output
        for contract_name in compiler_output[path].keys()
    }


def inline_source(
    name: str, compiler_output: Dict[str, Any], package_root_dir: Optional[Path] = None
) -> Manifest:
    """
    Return a copy of manifest with added field to
    "sources": {relative_source_path: contract_source_data}.

    If `package_root_dir` is not provided, cwd is expected to resolve the relative
    path to the source as defined in the compiler output.
    """
    return _inline_source(name, compiler_output, package_root_dir)


@curry
def _inline_source(
    name: str,
    compiler_output: Dict[str, Any],
    package_root_dir: Optional[Path],
    manifest: Manifest,
) -> Manifest:
    names_and_paths = get_names_and_paths(compiler_output)
    cwd = Path.cwd()
    source_path_suffix = names_and_paths[name]

    if package_root_dir:
        if (package_root_dir / source_path_suffix).is_file():
            source_data = (package_root_dir / source_path_suffix).read_text()
        else:
            raise ManifestBuildingError(
                "Contract source: {0} cannot be found in provided package_root_dir: {1}.".format(
                    source_path_suffix, package_root_dir
                )
            )
    elif (cwd / source_path_suffix).is_file():
        source_data = (cwd / source_path_suffix).read_text()
    else:
        raise ManifestBuildingError(
            "Contract source cannot be resolved, please make sure that the working "
            "directory is set to the correct directory or provide `package_root_dir`."
        )

    return assoc_in(manifest, ["sources", source_path_suffix], source_data)


def pin_source(
    name: str,
    compiler_output: Dict[str, Any],
    ipfs_backend: BaseIPFSBackend,
    package_root_dir: Optional[Path] = None,
) -> Manifest:
    """
    Pins source to IPFS and returns a copy of manifest with added field to
    "sources": {relative_source_path: IFPS URI}.

    If `package_root_dir` is not provided, cwd is expected to resolve the relative path
    to the source as defined in the compiler output.
    """
    return _pin_source(name, compiler_output, ipfs_backend, package_root_dir)


@curry
def _pin_source(
    name: str,
    compiler_output: Dict[str, Any],
    ipfs_backend: BaseIPFSBackend,
    package_root_dir: Optional[Path],
    manifest: Manifest,
) -> Manifest:
    names_and_paths = get_names_and_paths(compiler_output)
    source_path = names_and_paths[name]
    if package_root_dir:
        if not (package_root_dir / source_path).is_file():
            raise ManifestBuildingError(
                "Unable to find and pin contract source: {0} "
                "under specified package_root_dir: {1}.".format(
                    source_path, package_root_dir
                )
            )
        (ipfs_data,) = ipfs_backend.pin_assets(package_root_dir / source_path)
    else:
        cwd = Path.cwd()
        if not (cwd / source_path).is_file():
            raise ManifestBuildingError(
                "Unable to find and pin contract source: {0} "
                "current working directory: {1}.".format(source_path, cwd)
            )
        (ipfs_data,) = ipfs_backend.pin_assets(cwd / source_path)

    return assoc_in(
        manifest, ["sources", source_path], "ipfs://{0}".format(ipfs_data["Hash"])
    )


#
# Contract Types
#


def contract_type(
    name: str,
    compiler_output: Dict[str, Any],
    alias: Optional[str] = None,
    abi: Optional[bool] = False,
    compiler: Optional[bool] = False,
    contract_type: Optional[bool] = False,
    deployment_bytecode: Optional[bool] = False,
    natspec: Optional[bool] = False,
    runtime_bytecode: Optional[bool] = False,
) -> Manifest:
    """
    Returns a copy of manifest with added contract_data field as specified by kwargs.
    If no kwargs are present, all available contract_data found in the compiler output
    will be included.

    To include specific contract_data fields, add kwarg set to True (i.e. `abi=True`)
    To alias a contract_type, include a kwarg `alias` (i.e. `alias="OwnedAlias"`)
    If only an alias kwarg is provided, all available contract data will be included.
    Kwargs must match fields as defined in the EthPM Spec (except "alias") if user
        wants to include them in custom contract_type.
    """
    contract_type_fields = {
        "contract_type": contract_type,
        "deployment_bytecode": deployment_bytecode,
        "runtime_bytecode": runtime_bytecode,
        "abi": abi,
        "natspec": natspec,
        "compiler": compiler,
    }
    selected_fields = [k for k, v in contract_type_fields.items() if v]
    return _contract_type(name, compiler_output, alias, selected_fields)


@curry
def _contract_type(
    name: str,
    compiler_output: Dict[str, Any],
    alias: Optional[str],
    selected_fields: Optional[List[str]],
    manifest: Manifest,
) -> Manifest:
    contracts_by_name = normalize_compiler_output(compiler_output)
    try:
        all_type_data = contracts_by_name[name]
    except KeyError:
        raise ManifestBuildingError(
            "Contract name: {0} not found in the provided compiler output.".format(name)
        )
    if selected_fields:
        contract_type_data = {
            k: v for k, v in all_type_data.items() if k in selected_fields
        }
    else:
        contract_type_data = all_type_data

    if alias:
        return assoc_in(
            manifest,
            ["contract_types", alias],
            assoc(contract_type_data, "contract_type", name),
        )
    return assoc_in(manifest, ["contract_types", name], contract_type_data)


def normalize_compiler_output(compiler_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return compiler output with normalized fields for each contract type,
    as specified in `normalize_contract_type`.
    """
    paths_and_names = [
        (path, contract_name)
        for path in compiler_output
        for contract_name in compiler_output[path].keys()
    ]
    paths, names = zip(*paths_and_names)
    if len(names) != len(set(names)):
        raise ManifestBuildingError(
            "Duplicate contract names were found in the compiler output."
        )
    return {
        name: normalize_contract_type(compiler_output[path][name])
        for path, name in paths_and_names
    }


@to_dict
def normalize_contract_type(
    contract_type_data: Dict[str, Any]
) -> Iterable[Tuple[str, Any]]:
    """
    Serialize contract_data found in compiler output to the defined fields.
    """
    yield "abi", contract_type_data["abi"]
    yield "deployment_bytecode", normalize_bytecode_object(
        contract_type_data["evm"]["bytecode"]
    )
    # todo support natspec, runtime_bytecode
    yield "natspec", {}


@to_dict
def normalize_bytecode_object(obj: Dict[str, Any]) -> Iterable[Tuple[str, Any]]:
    if obj["linkReferences"]:
        yield "link_references", process_link_references(
            obj["linkReferences"], obj["object"]
        )
        yield "bytecode", process_bytecode(obj["linkReferences"], obj["object"])
    else:
        yield "bytecode", add_0x_prefix(obj["object"])


def process_bytecode(link_refs: Dict[str, Any], bytecode: bytes) -> bytes:
    """
    Replace link_refs in bytecode with 0's.
    """
    all_offsets = [y for x in link_refs.values() for y in x.values()]
    # Link ref validation.
    validate_link_ref_fns = (
        validate_link_ref(ref["start"] * 2, ref["length"] * 2)
        for ref in cytoolz.concat(all_offsets)
    )
    cytoolz.pipe(bytecode, *validate_link_ref_fns)
    # Convert link_refs in bytecode to 0's
    link_fns = (
        replace_link_ref_in_bytecode(ref["start"] * 2, ref["length"] * 2)
        for ref in cytoolz.concat(all_offsets)
    )
    processed_bytecode = cytoolz.pipe(bytecode, *link_fns)
    return add_0x_prefix(processed_bytecode)


@cytoolz.curry
def replace_link_ref_in_bytecode(offset: int, length: int, bytecode: str) -> str:
    new_bytes = (
        bytecode[:offset] + "0" * length + bytecode[offset + length :]  # noqa: E203
    )
    return new_bytes


# todo pull all bytecode linking/validating across py-ethpm into shared utils
@to_list
def process_link_references(
    link_refs: Dict[str, Any], bytecode: str
) -> Iterable[Dict[str, Any]]:
    for link_ref in link_refs.values():
        yield normalize_link_ref(link_ref, bytecode)


def normalize_link_ref(link_ref: Dict[str, Any], bytecode: str) -> Dict[str, Any]:
    name = list(link_ref.keys())[0]
    return {
        "name": name,
        "length": 20,
        "offsets": normalize_offsets(link_ref, bytecode),
    }


@to_list
def normalize_offsets(data: Dict[str, Any], bytecode: str) -> Iterable[List[int]]:
    for link_ref in data.values():
        for ref in link_ref:
            yield ref["start"]


@cytoolz.curry
def validate_link_ref(offset: int, length: int, bytecode: str) -> str:
    slot_length = offset + length
    slot = bytecode[offset:slot_length]
    if slot[:2] != "__" and slot[-2:] != "__":
        raise ValidationError(
            "Slot: {0}, at offset: {1} of length: {2} is not a valid "
            "link_ref that can be replaced.".format(slot, offset, length)
        )
    return bytecode


#
# Formatting
#


@curry
def validate(manifest: Manifest) -> Manifest:
    """
    Return a validated manifest against the V2-specification schema.
    """
    validate_manifest_against_schema(manifest)
    return manifest


@curry
def return_package(w3: Web3, manifest: Manifest) -> Package:
    """
    Return a Package object instantiated with the provided manifest and web3 instance.
    """
    return Package(manifest, w3)


def to_disk(
    manifest_root_dir: Optional[Path] = None,
    manifest_name: Optional[str] = None,
    prettify: Optional[bool] = False,
) -> Manifest:
    """
    Write the active manifest to disk
    Defaults
    - Writes manifest to cwd unless Path is provided as manifest_root_dir.
    - Writes manifest with a filename of Manifest[version].json unless a desired
      manifest name (which must end in json) is provided as manifest_name.
    - Writes the minified manifest version to disk unless prettify is set to True.
    """
    return _to_disk(manifest_root_dir, manifest_name, prettify)


@curry
def _to_disk(
    manifest_root_dir: Optional[Path],
    manifest_name: Optional[str],
    prettify: Optional[bool],
    manifest: Manifest,
) -> Manifest:
    if manifest_root_dir:
        if manifest_root_dir.is_dir():
            cwd = manifest_root_dir
        else:
            raise ManifestBuildingError(
                "Manifest root directory: {0} cannot be found, please "
                "provide a valid directory for writing the manifest to disk. "
                "(Path obj // leave manifest_root_dir blank to default to cwd)".format(
                    manifest_root_dir
                )
            )
    else:
        cwd = Path.cwd()

    if manifest_name:
        if not manifest_name.lower().endswith(".json"):
            raise ManifestBuildingError(
                "Invalid manifest name: {0}. All manifest names must end in .json".format(
                    manifest_name
                )
            )
        disk_manifest_name = manifest_name
    else:
        disk_manifest_name = manifest["version"] + ".json"

    if prettify:
        contents = json.dumps(manifest, sort_keys=True, indent=4)
    else:
        contents = json.dumps(manifest, sort_keys=True, separators=(",", ":"))

    if (cwd / disk_manifest_name).is_file():
        raise ManifestBuildingError(
            "Manifest: {0} already exists in cwd: {1}".format(disk_manifest_name, cwd)
        )
    (cwd / disk_manifest_name).write_text(contents)
    return manifest
