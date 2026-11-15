"""The pool root and the proof of one position (spec VP1 section 3.1).

Pure functions. The pool root commits to the set of images of a pool
version, in the canonical ascending sequence of the pool index. Each
leaf has a secret salt, so a proof that names the hash of a sibling
names no other image to a reader who tries image names.

Each digest is the SHA-256 of a text, written as lowercase hex, so a
reader with any SHA-256 tool can calculate it again:

    salt  = HMAC-SHA256(pool_key, image_id)            (hex)
    leaf  = SHA-256("vp1-leaf:" + salt + ":" + image_id)
    node  = SHA-256("vp1-node:" + left + right)
    root  = SHA-256("vp1-root:" + N + ":" + top)

A level with an odd count carries its last node up unchanged. A proof
is a sequence of steps "L:<hex>" or "R:<hex>": the sibling on the left
or on the right.
"""

import hashlib
import hmac
from collections.abc import Sequence


class ProofError(ValueError):
    """A proof does not have the shape that its position needs."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def leaf_salt(pool_key: bytes, image_id: str) -> str:
    """The secret salt of one leaf: HMAC-SHA256 of the image id, hex."""
    return hmac.new(pool_key, image_id.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def leaf_digest(salt: str, image_id: str) -> str:
    return _sha(f"vp1-leaf:{salt}:{image_id}")


def node_digest(left: str, right: str) -> str:
    return _sha(f"vp1-node:{left}{right}")


def root_digest(count: int, top: str) -> str:
    return _sha(f"vp1-root:{count}:{top}")


def _levels(leaves: Sequence[str]) -> list[list[str]]:
    """Each level of the tree, from the leaves up to the top node."""
    if not leaves:
        raise ProofError("a pool root needs at least one image")
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        below = levels[-1]
        above = [node_digest(below[i], below[i + 1])
                 for i in range(0, len(below) - 1, 2)]
        if len(below) % 2:
            above.append(below[-1])
        levels.append(above)
    return levels


def _leaves(image_ids: Sequence[str], pool_key: bytes) -> list[str]:
    return [leaf_digest(leaf_salt(pool_key, image_id), image_id)
            for image_id in image_ids]


def pool_root(image_ids: Sequence[str], pool_key: bytes) -> str:
    """The pool root of the images, in the sequence given."""
    top = _levels(_leaves(image_ids, pool_key))[-1][0]
    return root_digest(len(image_ids), top)


def proof_of(image_ids: Sequence[str], pool_key: bytes,
             index: int) -> tuple[str, ...]:
    """The proof of the leaf at index, from the leaf up to the top."""
    if not 0 <= index < len(image_ids):
        raise ProofError(
            f"index {index} is not in a pool of {len(image_ids)}")
    steps = []
    position = index
    for level in _levels(_leaves(image_ids, pool_key))[:-1]:
        carried = position == len(level) - 1 and len(level) % 2
        if not carried:
            if position % 2:
                steps.append(f"L:{level[position - 1]}")
            else:
                steps.append(f"R:{level[position + 1]}")
        position //= 2
    return tuple(steps)


def root_from_proof(image_id: str, salt: str, index: int, count: int,
                    steps: Sequence[str]) -> str:
    """The pool root that a leaf and its proof give, or ProofError.

    The position and the count say at which levels the node carries
    up with no step, so a proof with a step too many or too few, or a
    step on the wrong side, raises.
    """
    if not 0 <= index < count:
        raise ProofError(f"index {index} is not in a pool of {count}")
    node = leaf_digest(salt, image_id)
    position, width = index, count
    remaining = list(steps)
    while width > 1:
        carried = position == width - 1 and width % 2
        if not carried:
            if not remaining:
                raise ProofError("the proof ends before the top")
            side, _, sibling = remaining.pop(0).partition(":")
            expected = "L" if position % 2 else "R"
            if side != expected or len(sibling) != 64:
                raise ProofError(
                    f"expected a step {expected}:<64 hex>, got {side}:...")
            node = node_digest(sibling, node) if side == "L" \
                else node_digest(node, sibling)
        position //= 2
        width = (width + 1) // 2
    if remaining:
        raise ProofError("the proof has steps after the top")
    return root_digest(count, node)


def proof_agrees(image_id: str, salt: str, index: int, count: int,
                 steps: Sequence[str], expected_root: str) -> bool:
    """True when the leaf and its proof give the expected pool root."""
    try:
        return root_from_proof(image_id, salt, index, count,
                               steps) == expected_root
    except ProofError:
        return False
