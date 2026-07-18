import sqlite3
import csv
import logging
import urllib3
import sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
http = urllib3.PoolManager()

# The direct, updated nightly clinical evidence release URL
CIVIC_EVIDENCE_URL = "https://civicdb.org/downloads/nightly/nightly-AcceptedClinicalEvidenceSummaries.tsv"
CIVIC_VARIANT_URL = "https://civicdb.org/downloads/nightly/nightly-VariantSummaries.tsv"
CIVIC_MP_URL = "https://civicdb.org/downloads/nightly/nightly-MolecularProfileSummaries.tsv"

def init_civic_database(db_path: str = "knowledge_base.db"):
    """Sets up the pristine 13-column schema layout."""
    logging.info(f"Initializing relational database schema at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("DROP TABLE IF EXISTS civic_evidence")
    cursor.execute("""
        CREATE TABLE civic_evidence (
            id TEXT PRIMARY KEY,
            citation TEXT,
            citation_id INTEGER,
            disease TEXT,
            evidence_direction TEXT,
            evidence_level TEXT,
            evidence_statement TEXT,
            evidence_type TEXT,
            molecular_profile TEXT,
            phenotypes TEXT,
            rating INTEGER,
            significance TEXT,
            status TEXT,
            therapies TEXT,
            therapy_interaction_type TEXT,
            variant_origin TEXT
        )
    """)
    cursor.execute("CREATE INDEX idx_mol_prof ON civic_evidence(molecular_profile);")
    conn.commit()
    conn.close()

def seed_database_from_tsv(db_path: str = "knowledge_base.db"):
    """
    Downloads the nightly clinical summaries TSV file, matches headers dynamically,
    and bulk-inserts the records into SQLite.
    """
    logging.info("Downloading nightly clinical evidence summaries directly from CIViC...")
    
    #try:
    response = http.request('GET', CIVIC_EVIDENCE_URL)
    if response.status != 200:
        logging.error(f"Failed to fetch TSV file. Status: {response.status}")
        return

    # Decode data stream split by rows
    tsv_lines = response.data.decode('utf-8').splitlines()
    reader = csv.DictReader(tsv_lines, delimiter='\t')

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    inserted_counter = 0

    for row in reader:
        print(row)
        sys.exit()
    #         # Map the TSV headers to your exact 13-column schema definitions
    #         evidence_id = row.get("evidence_id") or row.get("id")
    #         if not evidence_id:
    #             continue # Skip row if identifier is completely absent
    #         citation = row.get("citation") or "No citations"
    #         citation_id = row.get("citation_id") or "U"
    #         disease_name = row.get("disease") or "Unknown Disease"
    #         evidence_dir = row.get("evidence_direction") or "Unknown Direction"
    #         evidence_lvl = row.get("evidence_level") or "U"
    #         evidence_st = row.get("evidence_statement") or "No evidence statement provided."
    #         evidence_typ = row.get("evidence_type") or "Unknown Type"
    #         mp_name = row.get("molecular_profile") or "Unknown MP"
    #         phenotype = row.get("phenotypes") or "Unknown Phenotypes"
    #         try:
    #             rating_val = int(row.get("rating", 0))
    #         except (ValueError, TypeError):
    #             rating_val = 0
    #         significance_val = row.get("significance") or "Unknown Significance"
    #         status_val = row.get("status") or "Accepted"
    #         therapies_str = row.get("therapies") or "None Annotated"
    #         therapy_interaction = row.get("therapy_interaction_type") or "N/A"
    #         origin_val = row.get("variant_origin") or "Unknown Origin"

    #         cursor.execute("""
    #             INSERT OR REPLACE INTO civic_evidence 
    #             (id, citation, citation_id, disease, evidence_direction, 
    #              evidence_level, evidence_statement, evidence_type, molecular_profile, 
    #              phenotypes, rating, significance, status, therapies, therapy_interaction_type, variant_origin)
    #             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    #         """, (
    #             evidence_id, citation, citation_id, disease_name, evidence_dir,evidence_lvl, evidence_st,
    #              evidence_typ, mp_name, phenotype, rating_val, significance_val, status_val, therapies_str, therapy_interaction,origin_val
    #         ))
    #         inserted_counter += 1

    #     conn.commit()
    #     conn.close()
    #     logging.info(f"✨ Successfully compiled database! Loaded {inserted_counter} high-fidelity clinical summaries.")

    # except Exception as e:
    #     logging.error(f"TSV Ingestion routine halted prematurely: {str(e)}")

if __name__ == "__main__":
    init_civic_database()
    seed_database_from_tsv()