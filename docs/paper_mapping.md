# Paper-to-Code Mapping

This document maps the revised manuscript *Efficient Construction of
Perfect-Contrast XOR-Based Visual Cryptography via Share Allocation and
Recovery Relations* to the implementation.

| Manuscript object | Implementation |
|---|---|
| Access-structure normalization | `src/sgsr_xvcs/access.py`, `normalise_access_structure` in `core.py` |
| Canonical participant partition / restricted-growth-string allocation | `_restricted_growth_surjections` in `tables.py` |
| Qualified XOR signature | `_assignment_profile` in `sgsr.py` |
| Maximal-forbidden observed-type mask | `_assignment_profile` in `sgsr.py` |
| Induced affine recovery family | `_safe_qualified_induced_recovery_matrices` in `sgsr.py` |
| Exact affine realization by reduced row-echelon form over the binary field GF(2) | `_cached_type_formulas` and `_formulas_for_region` |
| Coverage deduplication and dominance | `_optimize_sgsr_impl` and `_finish_matrix_optimization` |
| Exact set cover | `_solve_ilp` in `tables.py` |
| Independent security verification | `verify_scheme` in `core.py` |
| Complete-threshold perfect-hash-family specialization | `threshold.py` |
| Shen-style conflict-pruned cross-check | `shen.py` |
| Construction serialization | `construction_io.py` |
| Image realization and reconstruction | `images.py` |

## Revised signature semantics

The implementation intentionally has no equal-cardinality blocking rule. For
one allocation `L`, if qualified coalitions `Q1` and `Q2` satisfy

```text
sigma_L(Q1) = sigma_L(Q2) != 0,
```

then the coalitions XOR the same share-type expression. A recovery table that
contains this signature therefore covers both coalitions, regardless of their
sizes. Candidate validity depends only on:

1. exclusion of the zero signature;
2. affine closure consistency and exact GF(2) realization; and
3. absence of a recovery row contained in a maximal-forbidden observed mask.

`tests/test_signature_reuse.py` is the regression test for this rule.

## Exactness scope

The general optimality statement implemented here is scoped to a region-wise
linear XOR-based visual cryptography model with one linear XOR share per participant in each region,
region-wise perfect secrecy for forbidden coalitions, and exact unit-cost set
cover over minimal qualified coalitions. The code does not turn this theorem
into a claim about nonlinear schemes or cross-region algebraic coupling.

The threshold solver is a structured perfect-hash-family specialization: one share type per
participant per region, exactly `k` types, and recovery when a `k`-coalition
obtains all `k` types. Its solver certificate proves optimality inside this
specialization. Equality with the broader general linear optimum requires an
additional threshold-normalization theorem.

## Experimental synchronization

Deleting equal-cardinality blocking changes the candidate family. Therefore
all candidate counts, nondominated coverage families, runtimes, memory results,
and final pixel-expansion tables intended for the paper must be generated again
with this revision. The example JSON and PNG files in `docs/assets` validate
functionality only and must not be cited as the paper's performance data.
