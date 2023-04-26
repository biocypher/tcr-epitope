# https://vdjdb.cdr3.net/
# complex.id	Gene	CDR3	V	J	Species	MHC A	MHC B	MHC class	Epitope	Epitope gene	Epitope species	Reference	Method	Meta	CDR3fix	Score
# 1	TRB	CASSYLPGQGDHYSNQPQHF	TRBV13*01	TRBJ1-5*01	HomoSapiens	HLA-B*08	B2M	MHCI	FLKEKGGL	Nef	HIV-1	PMID:15596521	{"frequency": "", "identification": "tetramer-sort", "sequencing": "sanger", "singlecell": "", "verification": "antigen-loaded-targets"}	{"cell.subset": "CD8+", "clone.id": "", "donor.MHC": "HLA-A*02:01,HLA-A*24:02;HLA-B*08:01,HLA-B*5701;HLA-Cw*06:02,HLA-Cw*07:01;HLA-DRB*07:01,HLA-DRB*13:01", "donor.MHC.method": "", "epitope.id": "", "replica.id": "", "samples.found": 1, "structure.id": "", "studies.found": 1, "study.id": "", "subject.cohort": "HIV+", "subject.id": "005", "tissue": "PBMC"}	{"cdr3": "CASSYLPGQGDHYSNQPQHF", "cdr3_old": "CASSYLPGQGDHYSNQPQH", "fixNeeded": true, "good": true, "jCanonical": true, "jFixType": "Realign", "jId": "TRBJ1-5*01", "jStart": 13, "oldJFixType": "FixAdd", "oldJStart": 14, "vCanonical": true, "vEnd": 4, "vFixType": "NoFixNeeded", "vId": "TRBV13*01"}	2
# 0	TRB	CASSFEAGQGFFSNQPQHF	TRBV13*01	TRBJ1-5*01	HomoSapiens	HLA-B*08	B2M	MHCI	FLKEKGGL	Nef	HIV-1	PMID:15596521	{"frequency": "", "identification": "tetramer-sort", "sequencing": "sanger", "singlecell": "", "verification": "antigen-loaded-targets"}	{"cell.subset": "CD8+", "clone.id": "", "donor.MHC": "HLA-A*01:01,HLA-A*02:01;HLA-B*08:01,HLA-B*57:01;HLA-Cw*06:02,HLA-Cw*07:01;HLA-DRB*08:03:2,HLA-DRB*15:01:1", "donor.MHC.method": "", "epitope.id": "", "replica.id": "", "samples.found": 1, "structure.id": "", "studies.found": 1, "study.id": "", "subject.cohort": "HIV+", "subject.id": "065", "tissue": "PBMC"}	{"cdr3": "CASSFEAGQGFFSNQPQHF", "cdr3_old": "CASSFEAGQGFFSNQPQH", "fixNeeded": true, "good": true, "jCanonical": true, "jFixType": "Realign", "jId": "TRBJ1-5*01", "jStart": 12, "oldJFixType": "FixAdd", "oldJStart": 13, "vCanonical": true, "vEnd": 4, "vFixType": "NoFixNeeded", "vId": "TRBV13*01"}	2

import pandas as pd

class VDJDBAdapter:
    def __init__(self) -> None:
        self.vdjdb = pd.read_csv('data/SearchTable-2023-04-26 14_23_16.112.tsv', sep='\t')

        # new table with only unique Gene and CDR3 columns (nodes)
        self.vdjdb_sequence = self.vdjdb[['Gene', 'CDR3']].drop_duplicates()

        # new table with only unique Epitope columns (nodes)
        self.vdjdb_epitope = self.vdjdb[['Epitope']].drop_duplicates()

        # new table with only unique Gene, CDR3, Epitope columns (edges)
        self.vdjdb_edge = self.vdjdb[['Gene', 'CDR3', 'Epitope']].drop_duplicates()

    def get_nodes(self):
        for row in self.vdjdb_sequence.itertuples():
            _id = "_".join([row.Gene, row.CDR3])
            _type = row.Gene
            _props = {}
            
            yield (_id, _type, _props)

        for row in self.vdjdb_epitope.itertuples():
            _id = row.Epitope
            _type = 'Epitope'
            _props = {}
            
            yield (_id, _type, _props)

    def get_edges(self):
        for row in self.vdjdb_edge.itertuples():
            _from = "_".join([row.Gene, row.CDR3])
            _to = row.Epitope
            _type = 'TCR_Sequence_To_Epitope'
            _props = {}
            
            yield (None, _from, _to, _type, _props)
