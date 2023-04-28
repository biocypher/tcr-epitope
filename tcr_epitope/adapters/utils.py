AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")


def validate_peptide_sequence(seq: str) -> bool:
    """
    Checks if a given sequence is a valid peptide sequence.
    """
    return all([aa in AMINO_ACIDS for aa in seq])
