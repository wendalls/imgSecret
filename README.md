# SARR-XVCS: Anonymous Reproducibility Package

This anonymous repository accompanies the manuscript *Efficient Construction
of Perfect-Contrast XOR-Based Visual Cryptography via Share Allocation and
Recovery Relations*. It implements:

- coverage-complete candidate generation for general access structures;
- exact downstream minimum-column selection;
- the complete-threshold perfect-hash-family formulation;
- binary secret-image encoding into expanded participant shares; and
- coalition XOR reconstruction either through one automatically selected
  recovering region or over the complete expanded shares as one whole image.

The implementation targets the region-wise linear, single-share-per-participant,
perfect-contrast XOR model defined in the manuscript. Threshold results are
optimal within the perfect-hash-family formulation.

## Installation

Python 3.10 or newer is required.

```bash
python -m pip install -e .
```

For development checks:

```bash
python -m pip install -e ".[dev]"
ruff check src tests examples experiments
pytest
```

## Reproduce the mixed-cardinality general-access example

The included input has

```text
Q- = {{1,2}, {1,3}, {1,4,5}, {2,3,4}, {2,3,5}}.
```

The following command computes the complete candidate family, solves the exact
downstream cover, and encodes `examples/secret.png` with the resulting optimal
construction:

```bash
sarr-xvcs image-general \
  examples/mixed_cardinality_n5.json \
  examples/phone.png \
  output/mixed-n5 \
  --seed 20260919
```

Recover a secret through the first valid region contained in coalition `{1,4,5}`:

```bash
sarr-xvcs recover-image output/mixed-n5 1,4,5 \
  --output-name recovered_1_4_5.png
```

XOR the complete expanded shares of the same coalition into one image:

```bash
sarr-xvcs xor-image output/mixed-n5 1,4,5 \
  --output-name coalition_1_4_5_xor.png
```

The command writes one complete XOR image with the same dimensions as an
expanded participant share: height `source_height` and width
`m * source_width`, where `m` is the optimal pixel expansion. The complete
region images are concatenated horizontally as `[R1 | R2 | ... | Rm]`; they
are neither interleaved by column nor saved as separate files.

## Reproduce the complete `(3,6)` threshold example

```bash
sarr-xvcs image-threshold 3 6 \
  examples/secret.png \
  output/threshold-3-6 \
  --seed 20260919

sarr-xvcs xor-image output/threshold-3-6 1,3,5 \
  --output-name coalition_1_3_5_xor.png
```

The result is one complete three-region XOR image arranged as
`[R1 | R2 | R3]`. For this coalition, region block 1 reproduces the secret and
the other blocks are non-recovering, but the stored output remains a single
expanded image.

## Construction-only commands

Save an optimized general-access construction without encoding an image:

```bash
sarr-xvcs general examples/mixed_cardinality_n5.json \
  --output output/mixed-n5-construction.json
```

Save an exact perfect-hash-family construction:

```bash
sarr-xvcs threshold 3 6 \
  --output output/threshold-3-6-construction.json
```

Omitting `--time-limit` requests an unlimited exact threshold solve. A
time-limited run reports lower and upper bounds separately and does not label a
merely feasible construction as optimal.

## Reproduce the manuscript threshold table

```bash
python experiments/verify_threshold_table.py
```

The generated certificate records, for every `2 <= k <= n <= 9` entry:

- selected canonical partition columns;
- exact lower bound and verified upper bound;
- solver status; and
- whether the solver itself closed the optimum.

The output is written to `results/threshold_phf_certificates.json`.

Verify the recovery behavior inside every whole expanded XOR image shown in the
manuscript and regenerate both contact sheets:

```bash
python experiments/verify_paper_images.py
python experiments/make_paper_figures.py
```

The verifier checks the recovery behavior embedded in each whole expanded XOR
image and distinct threshold-region random-mask fingerprints.

## Repository layout

```text
src/sgsr_xvcs/                 optimization and image implementation
examples/mixed_cardinality_n5.json
examples/phone.png             mixed-cardinality manuscript source secret
examples/secret.png            threshold manuscript source secret
experiments/                   table and figure reproduction scripts
results/                       archived numerical results and certificates
tests/                         correctness and regression tests
docs/                          model and image-workflow notes
```

## Anonymity and citation

The package contains no author names, affiliations, email addresses, local
machine paths, or repository-owner identifiers. Citation metadata intentionally
uses “Anonymous authors” for double-blind review and should be replaced only
after acceptance.

## License

MIT. See `LICENSE`.
