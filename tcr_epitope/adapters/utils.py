import gzip
import hashlib
import json
import os
import re
from datetime import datetime
from typing import List

import pandas as pd
from biocypher import APIRequest, BioCypher
from scirpy.io._datastructures import AirrCell

from .constants import REGISTRY_KEYS
from .mapping_utils import map_species_terms

AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")


def is_valid_peptide_sequence(seq: str) -> bool:
    """Checks if a given sequence is a valid peptide sequence."""
    if isinstance(seq, str) and len(seq) > 2:
        return all([aa in AMINO_ACIDS for aa in seq])
    else:
        return False


def process_cdr3_sequence(seq: str, is_igh: bool = False) -> str | None:
    if seq is None:
        return None

    # Clean and normalize the sequence
    seq = str(seq).upper().strip().replace(" ", "").replace("\n", "")

    # Validate that the sequence contains only valid amino acids (optional: define valid AAs if needed)
    if not is_valid_peptide_sequence(seq):
        return None

    # Check if sequence has a valid CDR3 format
    starts_with_c = seq.startswith("C")
    ends_with_fw = seq.endswith("F") or (is_igh and seq.endswith("W"))

    if starts_with_c and ends_with_fw:
        return seq

    # Pad the sequence appropriately
    seq = seq.lstrip("C")  # remove leading C if already present
    if is_igh:
        seq = seq.rstrip("FW")  # remove existing F or W if present
        return f"C{seq}W"
    else:
        seq = seq.rstrip("F")
        return f"C{seq}F"


def process_epitope_sequence(seq: str | None) -> str | None:
    """Process a sequence string to remove non-peptidic characters and validate it."""
    if seq is None:
        return None
    seq = str(seq)
    result = seq.split("+")[0]  # split_epitope_sequence
    result = result.upper()
    result = "".join(result.split())

    return result


def normalise_gene_name(gene: str) -> str:
    if pd.isna(gene):
        return None
    gene = gene.strip()
    # Replace TCRA → TRA, TCRB → TRB, etc.
    gene = re.sub(r"^TCR([ABGD])", r"TR\1", gene)
    # Remove allele annotation like *01 or *01_F
    gene = re.sub(r"\*.*$", "", gene)
    return gene


def harmonize_sequences(bc, table: pd.DataFrame) -> pd.DataFrame:
    """Preprocesses CDR3 sequences, epitope sequences, and gene names in a harmonized way."""
    # Clean CDR3 sequences (normalize junction_aas)
    for i in [1, 2]:
        cdr3_col = getattr(REGISTRY_KEYS, f"CHAIN_{i}_CDR3_KEY")
        type_col = getattr(REGISTRY_KEYS, f"CHAIN_{i}_TYPE_KEY")

        if cdr3_col in table.columns and type_col in table.columns:
            table[cdr3_col] = table.apply(
                lambda row: process_cdr3_sequence(row[cdr3_col], is_igh=(row[type_col] == "IGH")), axis=1
            )

    # Clean epitope sequences
    if REGISTRY_KEYS.EPITOPE_KEY in table.columns:
        table[REGISTRY_KEYS.EPITOPE_KEY] = table[REGISTRY_KEYS.EPITOPE_KEY].apply(process_epitope_sequence)

    # Normalize V and J genes
    vj_genes_cols = [
        REGISTRY_KEYS.CHAIN_1_V_GENE_KEY,
        REGISTRY_KEYS.CHAIN_1_J_GENE_KEY,
        REGISTRY_KEYS.CHAIN_2_V_GENE_KEY,
        REGISTRY_KEYS.CHAIN_2_J_GENE_KEY,
    ]
    for col in vj_genes_cols:
        if col in table.columns:
            table[col] = table[col].apply(normalise_gene_name)

    #####################################################################
    # Add iedb-epitopes mapping + species names
    # Map epitope sequences to IEDB IDs
    if REGISTRY_KEYS.EPITOPE_IEDB_ID_KEY not in table.columns:
        valid_epitopes = table[REGISTRY_KEYS.EPITOPE_KEY].dropna().drop_duplicates().tolist()
        if len(valid_epitopes) > 0:
            epitope_map = get_iedb_ids_batch(bc, valid_epitopes)

        # Apply the mapping to create the IEDB ID column
        iri_mapping = {epitope: data["iri"] for epitope, data in epitope_map.items()}

        organism_mapping = {
            epitope: data["organism"] for epitope, data in epitope_map.items() if data["organism"] is not None
        }

        # Apply IRI mapping
        table[REGISTRY_KEYS.EPITOPE_IEDB_ID_KEY] = table[REGISTRY_KEYS.EPITOPE_KEY].map(iri_mapping)

        # Apply organism mapping - this will only update rows where mapping exists and is not None
        # Original values are preserved for epitopes not in organism_mapping
        mapped_organisms = table[REGISTRY_KEYS.EPITOPE_KEY].map(organism_mapping)
        table[REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY] = mapped_organisms.fillna(table[REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY])

    # Apply manual mapping for antigen species keys
    if REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY in table.columns:
        antigen_species_map = map_species_terms(table[REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY].dropna().unique().tolist())
        table[REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY] = table[REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY].map(antigen_species_map)

    # Delete brackets from the antigen name
    if REGISTRY_KEYS.ANTIGEN_KEY in table.columns:
        table[REGISTRY_KEYS.ANTIGEN_KEY] = (
            table[REGISTRY_KEYS.ANTIGEN_KEY].str.replace(r"\[.*?\]|\(.*?\)", "", regex=True).str.strip()
        )

    return table


def get_iedb_ids_batch(bc: BioCypher, epitopes: list[str], chunk_size: int = 150) -> dict[str, int]:
    """Retrieve IEDB IDs for multiple epitopes using batched requests.

    First tries exact matches, then falls back to substring matches for unmatched epitopes.

    Args:
        bc: Biocypher instance for the donwnload
        epitopes: List of epitope sequences to query
        chunk_size: Size of chunks to break epitopes into (to avoid URL length limits)

    Returns:
        Dictionary mapping epitope sequences to their IEDB IDs (0 if not found)
    """
    base_url = "https://query-api.iedb.org/epitope_search"
    epitope_to_iedb = {}
    unmatched_epitopes = []
    epitopes = [e for e in epitopes if e is not None]

    # Step 1: Try exact matches first
    print("Mapping AA epitope sequences to IEDB IDs: exact matches...")

    for i in range(0, len(epitopes), chunk_size):
        chunk = epitopes[i : i + chunk_size]
        epitope_matches = _get_epitope_data(bc, chunk, base_url, match_type="exact")

        # Map results to the dictionary
        for epitope in chunk:
            epitope_to_iedb[epitope] = {
                "iri": f"seq:{epitope}",
                "organism": None,
            }  # Default value if not found

        for match in epitope_matches:
            # Handle both possible API return formats for epitope sequences
            if match["structure_descriptions"]:
                epitope_seq = match["structure_descriptions"][0]
            elif "linear_sequence" in match:
                epitope_seq = match["linear_sequence"]
            else:
                continue

            if epitope_seq in epitope_to_iedb:  # Only update if it's one we requested
                if match.get("source_organism_name"):
                    organism = match.get("source_organism_name").split("|")[0].strip()
                else:
                    organism = None

                epitope_to_iedb[epitope_seq] = {
                    "iri": f"iedb:{match['structure_id']}",
                    "organism": organism,
                }

    # Step 2: Collect epitopes without matches and try string matching
    unmatched_epitopes = [ep for ep, info in epitope_to_iedb.items() if info["iri"] == f"seq:{ep}"]

    if unmatched_epitopes:
        print(
            f"Found {len(epitopes) - len(unmatched_epitopes)} exact IEDB ID matches.",
            f"Trying substring matches for {len(unmatched_epitopes)} remaining epitopes...",
        )
        chunk_size = chunk_size // 2

        for i in range(0, len(unmatched_epitopes), chunk_size):
            chunk = unmatched_epitopes[i : i + chunk_size]
            substring_matches = _get_epitope_data(bc, chunk, base_url, match_type="substring")

            for epitope_seq in chunk:
                best_match = None
                min_length = float("inf")

                # Find matches where the epitope is a substring
                for match in substring_matches:
                    if epitope_seq in match["linear_sequence"] and len(match["linear_sequence"]) < min_length:
                        best_match = match
                        min_length = len(match["linear_sequence"])

                # Update the dictionary if a match was found
                if best_match:
                    if best_match.get("source_organism_name"):
                        organism = best_match.get("source_organism_name").split("|")[0].strip()
                    else:
                        organism = None

                    epitope_to_iedb[epitope_seq] = {
                        "iri": f"iedb:{best_match['structure_id']}",
                        "organism": organism,
                    }

    # Final statistics
    matched_count = sum(1 for ep, info in epitope_to_iedb.items() if info["iri"].startswith("iedb:"))
    print(
        f"Final results: {matched_count} of {len(epitopes)} epitopes matched to IEDB IDs ({matched_count / len(epitopes) * 100:.1f}%)"
    )
    return epitope_to_iedb


def _get_epitope_data(bc: BioCypher, epitopes: list[str], base_url: str, match_type: str = "exact") -> list[dict]:
    """Get epitope data.

    Args:
        bc: Biocypher instance for the donwnload
        epitopes: List of epitope sequences to query
        base_url: Base URL for the API endpoint
        match_type: Type of matching to perform ("exact" or "substring")

    Returns:
        List of epitope data dictionaries
    """
    if match_type == "exact":
        request_hash = hashlib.md5("_".join(sorted(epitopes)).encode()).hexdigest()
        request_name = f"iedb_exact_matches_{request_hash}"
        epitope_list = f"({','.join([f'{e}' for e in epitopes])})"
        check = f"linear_sequence=in.{epitope_list}"
        url = f"{base_url}?{check}&select=structure_id,structure_descriptions,linear_sequence,source_organism_name&order=structure_id"
        print(f"Request URL: {url[:100]}..." if len(url) > 100 else f"Request URL: {url}")

    else:
        request_hash = hashlib.md5("_".join(sorted(epitopes)).encode()).hexdigest()
        request_name = f"iedb_substring_matches{request_hash}"
        conditions = [f"linear_sequence.ilike.*{e}*" for e in epitopes]
        check = f"or=({','.join(conditions)})"
        url = f"{base_url}?{check}&select=structure_id,structure_descriptions,linear_sequence,source_organism_name&order=structure_id"

    try:
        iedb_request = APIRequest(
            name=request_name,
            url_s=[url],
            lifetime=30,
        )
        paths = bc.download(iedb_request)

        # Load the cached JSON file
        if paths and len(paths) > 0:
            with open(paths[0]) as f:
                return json.load(f)

    except Exception as e:
        print(f"API request failed: {e}")
        return []


def save_airr_cells_json(airrcells: List[AirrCell], directory: str) -> None:
    """
    Save a list of AirrCell objects to a compressed JSON file with auto-generated filename.

    Parameters
    ----------
    airrcells : List[AirrCell]
        List of AirrCell objects to save
    directory : str
        Directory path where to save the JSON file (e.g., "../data")
    """
    serialized_data = []

    for cell in airrcells:
        cell_data = {
            "cell_id": cell.cell_id,
            "cell_attributes": dict(cell),  # Gets all cell-level attributes
            "chains": cell.chains,
            "cell_attribute_fields": list(cell._cell_attribute_fields),
        }
        serialized_data.append(cell_data)

    # Generate filename with current date
    current_date = datetime.now().strftime("%d%m%Y")  # Format: DDMMYYYY
    filename = f"airr_cells_{current_date}.json.gz"

    # Create full filepath
    filepath = os.path.join(directory, filename)

    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Save as compressed JSON
    with gzip.open(filepath, "wt", encoding="utf-8") as f:
        json.dump(serialized_data, f, indent=2, ensure_ascii=False)

    print(f"Compressed JSON saved to: {filepath}")


def save_airr_cells_csv(airr_cells: List, directory: str) -> None:
    """
    Convert list of AirrCell objects to CSV format and save as compressed file.

    Args:
        airr_cells: List of AirrCell objects
        directory: Directory path where to save the CSV file (e.g., "../data")
    """
    rows = []

    for cell in airr_cells:
        row = {}

        # Add cell-level attributes (no prefix needed)
        # AirrCell implements MutableMapping, so we can iterate through it
        for key, value in cell.items():
            row[key] = value

        # Process chains using the chains property
        tra_chain = None
        trb_chain = None
        other_chains = []

        for chain in cell.chains:
            locus = chain.get("locus", "").upper()

            if locus == "TRA":
                tra_chain = chain
            elif locus == "TRB":
                trb_chain = chain
            else:
                other_chains.append((locus, chain))

        # Add TRA chain with chain_1_ prefix
        if tra_chain:
            for key, value in tra_chain.items():
                prefixed_key = f"chain_1_{key}"
                row[prefixed_key] = value

        # Add TRB chain with chain_2_ prefix
        if trb_chain:
            for key, value in trb_chain.items():
                prefixed_key = f"chain_2_{key}"
                row[prefixed_key] = value

        # Add other chains with their locus as prefix
        for locus, chain in other_chains:
            for key, value in chain.items():
                prefixed_key = f"chain_{locus.lower()}_{key}"
                row[prefixed_key] = value

        rows.append(row)

    # Create DataFrame
    df = pd.DataFrame(rows)

    # Generate filename with current date
    current_date = datetime.now().strftime("%d%m%Y")  # Format: DDMMYYYY
    filename = f"airr_cells_tabular_{current_date}.csv.gz"

    # Create full filepath
    filepath = os.path.join(directory, filename)

    # Create directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Save to compressed CSV
    df.to_csv(filepath, index=False, compression="gzip")

    print(f"Compressed CSV saved to: {filepath}")
    print(f"Shape: {df.shape}")
