import os
from pathlib import Path

import pandas as pd
import pooch
from github import Github

from .base_adapter import BaseAdapter
from .constants import REGISTRY_KEYS
from .utils import validate_peptide_sequence


class VDJDBAdapter(BaseAdapter):
    """
    BioCypher adapter for the VDJdb database (https://vdjdb.cdr3.net/).
    
    Parameters
    ----------
    cache_dir
        The directory to store the downloaded IEDB data in. If `None`, a temporary
        directory will be created.
    test
        If `True`, only a subset of the data will be loaded for testing purposes.
    """

    REPO_NAME = "antigenomics/vdjdb-db"
    DB_DIR = "vdjdb_latest"
    DB_FNAME = "vdjdb.txt"

    def get_latest_release(self, save_dir: str) -> str:
        repo = Github().get_repo(self.REPO_NAME)
        db_url = repo.get_latest_release().get_assets()[0].browser_download_url

        path = Path(pooch.retrieve(
            db_url,
            None,
            fname=self.DB_DIR,
            path=save_dir,
            processor=pooch.Unzip(),
        )[0]).parent

        return os.path.join(path, self.DB_FNAME)
    
    def read_table(self, table_path: str, test: bool = False) -> pd.DataFrame:
        table = pd.read_csv(table_path, sep="\t")
        if test:
            table = table.sample(frac=0.1)
        table = table.where(pd.notnull(table), None)  # replace NaN with None

        rename_cols = {
            "gene": REGISTRY_KEYS.CHAIN_1_TYPE_KEY,
            "cdr3": REGISTRY_KEYS.CHAIN_1_CDR3_KEY,
            "antigen.epitope": REGISTRY_KEYS.EPITOPE_KEY,
            "antigen.gene": REGISTRY_KEYS.ANTIGEN_KEY,
            "antigen.species": REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY,
            "v.segm": REGISTRY_KEYS.CHAIN_1_V_GENE_KEY,
            "j.segm": REGISTRY_KEYS.CHAIN_1_J_GENE_KEY,
            "species": REGISTRY_KEYS.CHAIN_1_ORGANISM_KEY,
            "mhc.class": REGISTRY_KEYS.MHC_CLASS_KEY,
            "mhc.a": REGISTRY_KEYS.MHC_GENE_1_KEY,
            "mhc.b": REGISTRY_KEYS.MHC_GENE_2_KEY,
        }
        table = table.rename(columns=rename_cols)
        table = table[list(rename_cols.values())]

        # validate peptide sequences
        sequence_cols = [
            REGISTRY_KEYS.EPITOPE_KEY,
            REGISTRY_KEYS.CHAIN_1_CDR3_KEY,
        ]
        required_valid = [
            REGISTRY_KEYS.EPITOPE_KEY,
            REGISTRY_KEYS.CHAIN_1_CDR3_KEY,
        ]

        for col in sequence_cols:
            table[col] = table[col].apply(str)
            table[col] = table[col].apply(lambda x: x.upper())
            table[col] = table[col].apply(lambda x: "".join(x.split()))
            table[f"{col}_valid"] = table[col].apply(validate_peptide_sequence)

        for col in required_valid:
            table = table[table[f"{col}_valid"]]
            table = table[table[col] != "NAN"]

        return table

    def get_nodes(self):
        # chain 1
        yield from self._generate_nodes_from_table(
            subset_cols=[
                REGISTRY_KEYS.CHAIN_1_TYPE_KEY,
                REGISTRY_KEYS.CHAIN_1_CDR3_KEY,
                REGISTRY_KEYS.CHAIN_1_ORGANISM_KEY,
                REGISTRY_KEYS.CHAIN_1_V_GENE_KEY,
                REGISTRY_KEYS.CHAIN_1_J_GENE_KEY,
            ],
            unique_cols=[
                REGISTRY_KEYS.CHAIN_1_CDR3_KEY,
            ],
            property_cols=[
                REGISTRY_KEYS.CHAIN_1_ORGANISM_KEY,
                REGISTRY_KEYS.CHAIN_1_V_GENE_KEY,
                REGISTRY_KEYS.CHAIN_1_J_GENE_KEY,
            ],
        )

        # epitope
        yield from self._generate_nodes_from_table(
            subset_cols=[
                REGISTRY_KEYS.EPITOPE_KEY,
                REGISTRY_KEYS.ANTIGEN_KEY,
                REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY,
                REGISTRY_KEYS.MHC_CLASS_KEY,
                REGISTRY_KEYS.MHC_GENE_1_KEY,
                REGISTRY_KEYS.MHC_GENE_2_KEY,
            ],
            unique_cols=[
                REGISTRY_KEYS.EPITOPE_KEY,
            ],
            property_cols=[
                REGISTRY_KEYS.ANTIGEN_KEY,
                REGISTRY_KEYS.ANTIGEN_ORGANISM_KEY,
                REGISTRY_KEYS.MHC_CLASS_KEY,
                REGISTRY_KEYS.MHC_GENE_1_KEY,
                REGISTRY_KEYS.MHC_GENE_2_KEY,
            ],
        )

    def get_edges(self):
        # chain 1 - epitope
        yield from self._generate_edges_from_table(
            [
                REGISTRY_KEYS.CHAIN_1_TYPE_KEY,
                REGISTRY_KEYS.CHAIN_1_CDR3_KEY,
            ],
            REGISTRY_KEYS.EPITOPE_KEY,
            source_unique_cols=REGISTRY_KEYS.CHAIN_1_CDR3_KEY,
        )
