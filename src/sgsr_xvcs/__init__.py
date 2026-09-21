"""Share Allocation and Recovery Relations for XOR visual cryptography."""

from .access import maximal_forbidden, threshold_access_structure
from .api import (
    ComparisonResult,
    GeneralResult,
    compare_with_shen,
    optimize_access_structure,
    optimize_general,
)
from .construction_io import construction_payload, load_construction, save_construction
from .core import generate_binary_shares, reconstruct, verify_scheme
from .images import (
    encode_general_image,
    encode_threshold_image,
    load_binary_image,
    reconstruct_expanded_from_directory,
    reconstruct_from_directory,
    save_binary_image,
)
from .threshold import (
    MAX_PARTICIPANTS,
    ThresholdResult,
    build_threshold_incidence_matrix,
    optimize_threshold,
)

__all__ = [
    "MAX_PARTICIPANTS",
    "ComparisonResult",
    "GeneralResult",
    "ThresholdResult",
    "build_threshold_incidence_matrix",
    "compare_with_shen",
    "construction_payload",
    "encode_general_image",
    "encode_threshold_image",
    "generate_binary_shares",
    "load_binary_image",
    "load_construction",
    "maximal_forbidden",
    "optimize_access_structure",
    "optimize_general",
    "optimize_threshold",
    "reconstruct",
    "reconstruct_expanded_from_directory",
    "reconstruct_from_directory",
    "save_binary_image",
    "save_construction",
    "threshold_access_structure",
    "verify_scheme",
]

__version__ = "1.0.0"
