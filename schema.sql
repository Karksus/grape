-- =============================================================
-- CIViC schema — variant analyst agent
-- One Postgres instance doing both relational joins and vector
-- search (pgvector), per our design discussion.
-- =============================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- -------------------------------------------------------------
-- VARIANTS
-- Source: nightly-VariantSummaries.tsv
-- Note: for Fusion feature_type rows, `gene` is EMPTY — matching
-- must branch to feature_name / partner columns instead. See
-- ingest.py and the retrieval layer for the branch logic.
-- -------------------------------------------------------------
CREATE TABLE variants (
    variant_id                          INTEGER PRIMARY KEY,
    variant_civic_url                   TEXT,
    feature_type                        TEXT,          -- 'variant' (SNV/indel/etc) or 'Fusion'
    feature_id                          INTEGER,
    feature_name                        TEXT,          -- e.g. 'EWSR1::KLF15' for fusions
    feature_civic_url                   TEXT,
    variant_name                        TEXT,          -- raw 'variant' column, renamed to avoid ambiguity
    is_flagged                          BOOLEAN,
    variant_groups                      TEXT,
    variant_types                       TEXT,
    single_variant_molecular_profile_id INTEGER,       -- direct FK to the standalone MP; skip fuzzy text matching when present
    last_review_date                    TIMESTAMPTZ,
    gene                                TEXT,          -- empty for fusions, by design
    entrez_id                           INTEGER,
    chromosome                          TEXT,
    start_pos                           BIGINT,
    stop_pos                            BIGINT,
    reference_bases                     TEXT,
    variant_bases                       TEXT,
    representative_transcript           TEXT,
    ensembl_version                     TEXT,
    reference_build                     TEXT,
    hgvs_descriptions                   TEXT,
    allele_registry_id                  TEXT,
    clinvar_ids                         TEXT,
    ncit_id                             TEXT,
    five_prime_partner_status           TEXT,
    five_prime_partner                  TEXT,
    three_prime_partner_status          TEXT,
    three_prime_partner                 TEXT,
    vicc_compliant_name                 TEXT,
    five_prime_transcript               TEXT,
    five_prime_end_exon                 TEXT,
    five_prime_exon_offset              TEXT,
    five_prime_exon_offset_direction    TEXT,
    three_prime_transcript              TEXT,
    three_prime_start_exon              TEXT,
    three_prime_exon_offset             TEXT,
    three_prime_exon_offset_direction   TEXT,
    iscn_name                           TEXT
);

CREATE INDEX idx_variants_gene          ON variants (LOWER(gene));
CREATE INDEX idx_variants_variant_name  ON variants (LOWER(variant_name));
CREATE INDEX idx_variants_feature_name  ON variants (LOWER(feature_name));
CREATE INDEX idx_variants_feature_type  ON variants (feature_type);

-- variant_aliases is a comma-separated field in the raw TSV
-- (e.g. "RS113488022,VAL600GLU,V640E,VAL640GLU"). Exploded here
-- into one row per alias so lookups are exact-match, not
-- substring-on-a-blob.
CREATE TABLE variant_aliases (
    variant_id       INTEGER REFERENCES variants (variant_id),
    alias_raw        TEXT,
    alias_normalized TEXT       -- lowercased, trimmed — join key
);

CREATE INDEX idx_variant_aliases_norm ON variant_aliases (alias_normalized);

-- -------------------------------------------------------------
-- MOLECULAR PROFILES
-- Source: nightly-MolecularProfileSummaries.tsv
-- (filename not fully confirmed from public docs at write time —
--  verify the exact name on https://civicdb.org/releases before
--  running ingest.py; the download function takes it as a param.)
-- -------------------------------------------------------------
CREATE TABLE molecular_profiles (
    molecular_profile_id INTEGER PRIMARY KEY,
    name                  TEXT,          -- e.g. 'ROS1 G2032R AND SLC4A4::ROS1 Fusion'
    summary               TEXT,
    evidence_score        NUMERIC,       -- CIViC's own aggregate score — coarser than our per-evidence score, kept as a secondary signal
    last_review_date      TIMESTAMPTZ,
    is_flagged            BOOLEAN,
    aliases               TEXT
);

-- Explodes the MP's `variant_ids` field (e.g. "1271, 4628").
-- This is what lets us find COMPOUND profiles a variant
-- participates in, via exact variant_id match — not substring
-- search on the raw string (which would false-positive, e.g.
-- '127' inside '1271').
CREATE TABLE molecular_profile_variants (
    molecular_profile_id INTEGER REFERENCES molecular_profiles (molecular_profile_id),
    variant_id            INTEGER REFERENCES variants (variant_id),
    PRIMARY KEY (molecular_profile_id, variant_id)
);

CREATE INDEX idx_mpv_variant ON molecular_profile_variants (variant_id);

-- Explodes the MP's `evidence_item_ids` field the same way.
CREATE TABLE molecular_profile_evidence (
    molecular_profile_id INTEGER REFERENCES molecular_profiles (molecular_profile_id),
    evidence_id            INTEGER,
    PRIMARY KEY (molecular_profile_id, evidence_id)
);

CREATE INDEX idx_mpe_evidence ON molecular_profile_evidence (evidence_id);

-- -------------------------------------------------------------
-- EVIDENCE ITEMS
-- Source: nightly-AcceptedClinicalEvidenceSummaries.tsv
-- -------------------------------------------------------------
CREATE TABLE evidence_items (
    evidence_id                 INTEGER PRIMARY KEY,
    molecular_profile_id        INTEGER REFERENCES molecular_profiles (molecular_profile_id),
    molecular_profile_name      TEXT,      -- denormalized copy of the MP name, convenient for display
    disease                     TEXT,
    doid                        TEXT,
    phenotypes                  TEXT,
    therapies                   TEXT,
    therapy_interaction_type    TEXT,
    evidence_type                TEXT,     -- Diagnostic / Predictive / Prognostic / Predisposing / Oncogenic / Functional
    evidence_direction           TEXT,     -- Supports / Does Not Support
    evidence_level                TEXT,    -- A–E, see confidence scoring below
    significance                 TEXT,     -- Sensitivity/Response, Resistance, Oncogenicity, ... — DIFFERENT axis from evidence_type, don't conflate
    evidence_statement           TEXT,
    citation_id                  TEXT,     -- only trustworthy as a PubMed ID when source_type = 'PubMed'
    source_type                  TEXT,     -- 'PubMed', 'ASCO', etc.
    asco_abstract_id             TEXT,
    citation                     TEXT,     -- human-readable citation string — keep even when source_type != PubMed
    nct_ids                      TEXT,
    rating                       INTEGER,  -- 1–5
    evidence_status               TEXT,
    variant_origin                TEXT,
    last_review_date              TIMESTAMPTZ,
    evidence_civic_url            TEXT,
    molecular_profile_civic_url   TEXT,
    is_flagged                    BOOLEAN,
    confidence_score              NUMERIC  -- computed at ingest time from evidence_level + rating; kept SEPARATE from evidence_direction, see ingest.py
);

CREATE INDEX idx_evidence_mp       ON evidence_items (molecular_profile_id);
CREATE INDEX idx_evidence_disease  ON evidence_items (LOWER(disease));
CREATE INDEX idx_evidence_source   ON evidence_items (source_type);

-- -------------------------------------------------------------
-- DISEASE NAME EMBEDDINGS
-- Small table — one row per UNIQUE disease string in the dataset,
-- not one per evidence row. This is the "colon cancer" vs
-- "Colorectal Cancer" matching layer from our design discussion.
-- Dimension 1536 matches OpenAI text-embedding-3-small.
-- -------------------------------------------------------------
CREATE TABLE disease_embeddings (
    disease_name TEXT PRIMARY KEY,
    embedding    VECTOR(1536)
);

CREATE INDEX idx_disease_embedding ON disease_embeddings
    USING hnsw (embedding vector_cosine_ops);
