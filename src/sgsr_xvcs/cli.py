"""Command-line interface for SARR-XVCS."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .access import maximal_forbidden, threshold_access_structure
from .api import compare_with_shen, optimize_general
from .construction_io import construction_payload, load_construction, save_construction
from .core import ShareReuseScheme
from .images import (
    encode_general_image,
    encode_threshold_image,
    reconstruct_expanded_from_directory,
    reconstruct_from_directory,
)
from .threshold import optimize_threshold


def _load_access(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    people = tuple(data["participants"])
    qualified = tuple(frozenset(group) for group in data["qualified"])
    forbidden_data = data.get("forbidden")
    forbidden = (
        tuple(frozenset(group) for group in forbidden_data)
        if forbidden_data is not None
        else maximal_forbidden(people, qualified)
    )
    return people, qualified, forbidden


def _write(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=list))


def _emit_construction(result, output: str | None) -> None:
    if output:
        target = save_construction(result, output)
        _write({"construction": str(target), **result.to_dict()})
    else:
        _write(construction_payload(result))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sarr-xvcs",
        description="Share Allocation and Recovery Relations for XOR visual cryptography",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    general = sub.add_parser("general", help="solve a general access structure")
    general.add_argument("input", help="JSON access-structure file")
    general.add_argument("--max-pairs", type=int, default=2_000_000)
    general.add_argument("--max-share-types", type=int)
    general.add_argument("--output", help="write the complete construction JSON")
    general.add_argument(
        "--mode", choices=("standard", "mi", "mifr"), default="standard",
        help="qualified-coalition recovery semantics",
    )

    threshold = sub.add_parser("threshold", help="solve a complete (k,n) structure")
    threshold.add_argument("k", type=int)
    threshold.add_argument("n", type=int)
    threshold.add_argument(
        "--time-limit", type=float, default=None,
        help="optional solver limit in seconds; omitted means exact unlimited solve",
    )
    threshold.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    threshold.add_argument("--output", help="write the complete construction JSON")

    compare = sub.add_parser("compare", help="compare SARR with pruned Shen")
    compare.add_argument("input", help="JSON access-structure file")
    compare.add_argument("--max-pairs", type=int, default=2_000_000)
    compare.add_argument("--shen-max-checks", type=int, default=5_000_000)
    compare.add_argument("--shen-max-nodes", type=int, default=250_000)

    threshold_compare = sub.add_parser(
        "compare-threshold", help="compare both methods on a complete threshold structure"
    )
    threshold_compare.add_argument("k", type=int)
    threshold_compare.add_argument("n", type=int)
    threshold_compare.add_argument("--time-limit", type=float, default=None)
    threshold_compare.add_argument("--shen-max-checks", type=int, default=5_000_000)
    threshold_compare.add_argument("--shen-max-nodes", type=int, default=250_000)

    image_general = sub.add_parser(
        "image-general", help="solve a general structure and encode a binary image"
    )
    image_general.add_argument("input", help="JSON access-structure file")
    image_general.add_argument("secret", help="source image")
    image_general.add_argument("output", help="output directory")
    image_general.add_argument("--seed", type=int)
    image_general.add_argument("--max-pairs", type=int, default=2_000_000)
    image_general.add_argument(
        "--mode", choices=("standard", "mi", "mifr"), default="standard"
    )

    image_threshold = sub.add_parser(
        "image-threshold", help="solve a threshold structure and encode a binary image"
    )
    image_threshold.add_argument("k", type=int)
    image_threshold.add_argument("n", type=int)
    image_threshold.add_argument("secret", help="source image")
    image_threshold.add_argument("output", help="output directory")
    image_threshold.add_argument("--seed", type=int)
    image_threshold.add_argument("--time-limit", type=float, default=None)
    image_threshold.add_argument("--workers", type=int, default=os.cpu_count() or 1)

    encode = sub.add_parser(
        "encode-image", help="encode a secret image from a saved construction JSON"
    )
    encode.add_argument("construction", help="construction JSON from general or threshold")
    encode.add_argument("secret", help="source secret image")
    encode.add_argument("output", help="output directory for shares and metadata")
    encode.add_argument("--seed", type=int)
    encode.add_argument("--threshold", type=int, default=128)

    recover = sub.add_parser("recover-image", help="recover from saved share images")
    recover.add_argument("directory", help="directory containing metadata.json and shares")
    recover.add_argument(
        "coalition", help="comma-separated participant labels, for example 1,2,3"
    )
    recover.add_argument("--output-name", default="reconstructed.png")

    xor_image = sub.add_parser(
        "xor-image",
        help="XOR complete expanded shares into one whole image",
    )
    xor_image.add_argument(
        "directory", help="directory containing metadata.json and shares"
    )
    xor_image.add_argument(
        "coalition", help="comma-separated participant labels, for example 1,2,3"
    )
    xor_image.add_argument("--output-name", default="coalition_xor.png")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "general":
        people, qualified, forbidden = _load_access(args.input)
        result = optimize_general(
            qualified,
            forbidden,
            participants=people,
            max_share_types=args.max_share_types,
            max_candidate_pairs=args.max_pairs,
            reconstruction_mode=args.mode,
        )
        _emit_construction(result, args.output)
    elif args.command == "threshold":
        result = optimize_threshold(
            args.k,
            args.n,
            time_limit_seconds=args.time_limit,
            workers=args.workers,
        )
        _emit_construction(result, args.output)
    elif args.command == "compare":
        people, qualified, forbidden = _load_access(args.input)
        result = compare_with_shen(
            qualified,
            forbidden,
            participants=people,
            max_candidate_pairs=args.max_pairs,
            shen_max_checks=args.shen_max_checks,
            shen_max_nodes=args.shen_max_nodes,
        )
        _write(result.to_dict())
    elif args.command == "compare-threshold":
        people, qualified, forbidden = threshold_access_structure(args.k, args.n)
        result = compare_with_shen(
            qualified,
            forbidden,
            participants=people,
            shen_max_checks=args.shen_max_checks,
            shen_max_nodes=args.shen_max_nodes,
            threshold_time_limit_seconds=args.time_limit,
        )
        _write(result.to_dict())
    elif args.command == "image-general":
        people, qualified, forbidden = _load_access(args.input)
        result = optimize_general(
            qualified,
            forbidden,
            participants=people,
            max_candidate_pairs=args.max_pairs,
            reconstruction_mode=args.mode,
        )
        metadata = encode_general_image(
            args.secret, result, args.output, seed=args.seed
        )
        _write({"metadata": str(metadata), **result.to_dict()})
    elif args.command == "image-threshold":
        result = optimize_threshold(
            args.k,
            args.n,
            time_limit_seconds=args.time_limit,
            workers=args.workers,
        )
        metadata = encode_threshold_image(
            args.secret, result, args.output, seed=args.seed
        )
        _write({"metadata": str(metadata), **result.to_dict()})
    elif args.command == "encode-image":
        construction = load_construction(args.construction)
        if isinstance(construction, ShareReuseScheme):
            metadata = encode_general_image(
                args.secret,
                construction,
                args.output,
                seed=args.seed,
                threshold=args.threshold,
            )
        else:
            metadata = encode_threshold_image(
                args.secret,
                construction,
                args.output,
                seed=args.seed,
                threshold=args.threshold,
            )
        _write({"metadata": str(metadata)})
    elif args.command == "recover-image":
        coalition = [item.strip() for item in args.coalition.split(",") if item.strip()]
        output = reconstruct_from_directory(
            args.directory, coalition, output_name=args.output_name
        )
        _write({"reconstructed": str(output)})
    else:
        coalition = [item.strip() for item in args.coalition.split(",") if item.strip()]
        output = reconstruct_expanded_from_directory(
            args.directory,
            coalition,
            output_name=args.output_name,
        )
        _write({"expanded_xor": str(output)})


if __name__ == "__main__":
    main()
