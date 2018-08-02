import hashlib
from pathlib import Path
from urllib import parse

from ethpm.pb.ipfs_file_pb2 import Data, PBNode
from ethpm.utils.base58 import b58encode


def extract_ipfs_path_from_uri(value: str) -> str:
    """
    Return the path from an IPFS URI.
    Path = IPFS hash & following path.
    """
    parse_result = parse.urlparse(value)

    if parse_result.netloc:
        if parse_result.path:
            return "".join((parse_result.netloc, parse_result.path.rstrip("/")))
        else:
            return parse_result.netloc
    else:
        return parse_result.path.strip("/")


def is_ipfs_uri(value: str) -> bool:
    """
    Return a bool indicating whether or not the value is a valid IPFS URI.
    """
    parse_result = parse.urlparse(value)
    if parse_result.scheme != "ipfs":
        return False
    if not parse_result.netloc and not parse_result.path:
        return False

    return True


#
# Generate IPFS hash
# Lifted from https://github.com/ethereum/populus/blob/feat%2Fv2/populus/utils/ipfs.py
#


SHA2_256 = b"\x12"
LENGTH_32 = b"\x20"


def multihash(value: bytes) -> bytes:
    data_hash = hashlib.sha256(value).digest()

    multihash_bytes = SHA2_256 + LENGTH_32 + data_hash
    return multihash_bytes


def serialize_file(file_path: Path) -> PBNode:
    file_data = open(str(file_path), "rb").read()
    file_size = len(file_data)

    data_protobuf = Data(
        Type=Data.DataType.Value("File"), Data=file_data, filesize=file_size
    )
    data_protobuf_bytes = data_protobuf.SerializeToString()

    file_protobuf = PBNode(Links=[], Data=data_protobuf_bytes)

    return file_protobuf


def generate_file_hash(file_path: Path) -> str:
    file_protobuf = serialize_file(file_path)
    file_protobuf_bytes = file_protobuf.SerializeToString()
    file_multihash = multihash(file_protobuf_bytes)
    return b58encode(file_multihash)
