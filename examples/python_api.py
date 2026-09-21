from sgsr_xvcs import (
    encode_general_image,
    load_construction,
    maximal_forbidden,
    optimize_general,
    reconstruct_from_directory,
    save_construction,
)

participants = (1, 2, 3, 4)
qualified = ({1, 2}, {1, 3, 4})
forbidden = maximal_forbidden(participants, qualified)

result = optimize_general(
    qualified,
    forbidden,
    participants=participants,
)
save_construction(result, "output/general-construction.json")

construction = load_construction("output/general-construction.json")
encode_general_image(
    "examples/secret.png",
    construction,
    "output/general-shares",
    seed=7,
)
reconstruct_from_directory("output/general-shares", (1, 2))
