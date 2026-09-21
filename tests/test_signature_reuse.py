"""Regression tests for the revised paper's signature semantics."""

from sgsr_xvcs.sgsr import (
    _coverage_from_matrix,
    _safe_qualified_induced_recovery_matrices,
)


def test_one_signature_may_cover_different_coalition_sizes():
    # Q0={0,1} and Q1={0,2,3,4} have the same nonzero XOR signature under
    # labels (0,1,1,2,2).  The revised algorithm must not block the signature
    # merely because the coalition cardinalities are two and four.
    labels = (0, 1, 1, 2, 2)
    qualified_masks = ((1 << 0) | (1 << 1), sum(1 << i for i in (0, 2, 3, 4)))
    assert _coverage_from_matrix(frozenset({0b011}), labels, qualified_masks) == 0b11


def test_induced_closure_depends_on_security_not_cardinality():
    closures = _safe_qualified_induced_recovery_matrices(
        (0b011,),
        (0b001, 0b100),
    )
    assert (0b011,) in closures
