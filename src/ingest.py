import os
import sys
from io import StringIO
from datetime import datetime, timezone

import pandas as pd

EVIDENCE_URL = "https://civicdb.org/downloads/nightly/nightly-AcceptedClinicalEvidenceSummaries.tsv"
VARIANT_URL = "https://civicdb.org/downloads/nightly/nightly-VariantSummaries.tsv"
MOLECULAR_PROFILE_URL = "https://civicdb.org/downloads/nightly/nightly-MolecularProfileSummaries.tsv"

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://civic:civic@localhost:5432/civic")

# evidence_level -> numeric weight (A best, E weakest), per CIViC's own definitions
LEVEL_WEIGHT = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}

def fetch_tsv(url: str) -> pd.DataFrame:
    """Download a CIViC nightly TSV and load it with blanks preserved
    as empty strings, not NaN — CIViC's own blanks ARE empty strings,
    and treating them as NaN makes downstream string ops brittle."""
    import urllib.request

    print(f"  fetching {url}")
    with urllib.request.urlopen(url) as resp:
        raw = resp.read().decode("utf-8")
    df = pd.read_csv(StringIO(raw), sep="\t", dtype=str, keep_default_na=False, na_values=[])
    print(f"    -> {len(df)} rows, {len(df.columns)} columns")
    return df


def parse_list_field(raw: str) -> list[str]:
    """Split a comma-separated CIViC field into clean tokens.
    Handles the exact formatting seen in the samples, e.g.
    'RS113488022,VAL600GLU,V640E,VAL640GLU' or '1271, 4628'."""
    if not raw:
        return []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def normalize_token(s: str) -> str:
    return s.strip().lower()


def to_int(val: str):
    val = (val or "").strip()
    return int(val) if val.isdigit() else None


def to_bool(val: str):
    return (val or "").strip().lower() == "true"


def to_timestamp(val: str):
    val = (val or "").strip()
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def confidence_score(evidence_level: str, rating: str) -> float | None:
    """Combined confidence weight from evidence_level (A-E) and rating (1-5).
    Deliberately independent of evidence_direction — see design notes:
    a well-supported 'Does Not Support' should score as HIGH confidence,
    just negative direction. Direction is handled separately downstream,
    never folded into this scalar."""
    level_w = LEVEL_WEIGHT.get((evidence_level or "").strip().upper())
    rating_i = to_int(rating)
    if level_w is None and rating_i is None:
        return None
    if level_w is None:
        return float(rating_i)
    if rating_i is None:
        return float(level_w)
    return round((level_w + rating_i) / 2, 2)


def load_variants(conn, df: pd.DataFrame):
    from psycopg2.extras import execute_values
    rows = []
    alias_rows = []
    for _, r in df.iterrows():
        vid = to_int(r.get("variant_id", ""))
        if vid is None:
            continue
        rows.append((
            vid,
            r.get("variant_civic_url", ""),
            r.get("feature_type", ""),
            to_int(r.get("feature_id", "")),
            r.get("feature_name", ""),
            r.get("feature_civic_url", ""),
            r.get("variant", ""),
            to_bool(r.get("is_flagged", "")),
            r.get("variant_groups", ""),
            r.get("variant_types", ""),
            to_int(r.get("single_variant_molecular_profile_id", "")),
            to_timestamp(r.get("last_review_date", "")),
            r.get("gene", ""),
            to_int(r.get("entrez_id", "")),
            r.get("chromosome", ""),
            to_int(r.get("start", "")),
            to_int(r.get("stop", "")),
            r.get("reference_bases", ""),
            r.get("variant_bases", ""),
            r.get("representative_transcript", ""),
            r.get("ensembl_version", ""),
            r.get("reference_build", ""),
            r.get("hgvs_descriptions", ""),
            r.get("allele_registry_id", ""),
            r.get("clinvar_ids", ""),
            r.get("ncit_id", ""),
            r.get("5_prime_partner_status", ""),
            r.get("5_prime_partner", ""),
            r.get("3_prime_partner_status", ""),
            r.get("3_prime_partner", ""),
            r.get("vicc_compliant_name", ""),
            r.get("5_prime_transcript", ""),
            r.get("5_prime_end_exon", ""),
            r.get("5_prime_exon_offset", ""),
            r.get("5_prime_exon_offset_direction", ""),
            r.get("3_prime_transcript", ""),
            r.get("3_prime_start_exon", ""),
            r.get("3_prime_exon_offset", ""),
            r.get("3_prime_exon_offset_direction", ""),
            r.get("iscn_name", ""),
        ))
        for alias in parse_list_field(r.get("variant_aliases", "")):
            alias_rows.append((vid, alias, normalize_token(alias)))

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO variants (
                variant_id, variant_civic_url, feature_type, feature_id, feature_name,
                feature_civic_url, variant_name, is_flagged, variant_groups, variant_types,
                single_variant_molecular_profile_id, last_review_date, gene, entrez_id,
                chromosome, start_pos, stop_pos, reference_bases, variant_bases,
                representative_transcript, ensembl_version, reference_build, hgvs_descriptions,
                allele_registry_id, clinvar_ids, ncit_id, five_prime_partner_status,
                five_prime_partner, three_prime_partner_status, three_prime_partner,
                vicc_compliant_name, five_prime_transcript, five_prime_end_exon,
                five_prime_exon_offset, five_prime_exon_offset_direction, three_prime_transcript,
                three_prime_start_exon, three_prime_exon_offset, three_prime_exon_offset_direction,
                iscn_name
            ) VALUES %s
            ON CONFLICT (variant_id) DO UPDATE SET
                feature_type = EXCLUDED.feature_type,
                feature_name = EXCLUDED.feature_name,
                variant_name = EXCLUDED.variant_name,
                gene = EXCLUDED.gene,
                single_variant_molecular_profile_id = EXCLUDED.single_variant_molecular_profile_id,
                last_review_date = EXCLUDED.last_review_date
        """, rows)

        cur.execute("DELETE FROM variant_aliases")  # cheap table, full refresh is simplest
        if alias_rows:
            execute_values(cur, "INSERT INTO variant_aliases (variant_id, alias_raw, alias_normalized) VALUES %s", alias_rows)

    conn.commit()
    print(f"  loaded {len(rows)} variants, {len(alias_rows)} aliases")


def load_molecular_profiles(conn, df: pd.DataFrame):
    from psycopg2.extras import execute_values
    rows = []
    mp_variant_rows = []
    mp_evidence_rows = []
    for _, r in df.iterrows():
        mpid = to_int(r.get("molecular_profile_id", ""))
        if mpid is None:
            continue
        rows.append((
            mpid,
            r.get("name", ""),
            r.get("summary", ""),
            float(r["evidence_score"]) if r.get("evidence_score", "").strip() else None,
            to_timestamp(r.get("last_review_date", "")),
            to_bool(r.get("is_flagged", "")),
            r.get("aliases", ""),
        ))
        for vid_str in parse_list_field(r.get("variant_ids", "")):
            vid = to_int(vid_str)
            if vid is not None:
                mp_variant_rows.append((mpid, vid))
        for eid_str in parse_list_field(r.get("evidence_item_ids", "")):
            eid = to_int(eid_str)
            if eid is not None:
                mp_evidence_rows.append((mpid, eid))

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO molecular_profiles (
                molecular_profile_id, name, summary, evidence_score, last_review_date, is_flagged, aliases
            ) VALUES %s
            ON CONFLICT (molecular_profile_id) DO UPDATE SET
                name = EXCLUDED.name,
                summary = EXCLUDED.summary,
                evidence_score = EXCLUDED.evidence_score,
                last_review_date = EXCLUDED.last_review_date
        """, rows)

        cur.execute("DELETE FROM molecular_profile_variants")
        if mp_variant_rows:
            execute_values(cur, "INSERT INTO molecular_profile_variants (molecular_profile_id, variant_id) VALUES %s ON CONFLICT DO NOTHING", mp_variant_rows)

        cur.execute("DELETE FROM molecular_profile_evidence")
        if mp_evidence_rows:
            execute_values(cur, "INSERT INTO molecular_profile_evidence (molecular_profile_id, evidence_id) VALUES %s ON CONFLICT DO NOTHING", mp_evidence_rows)

    conn.commit()
    print(f"  loaded {len(rows)} molecular profiles, {len(mp_variant_rows)} MP-variant links, {len(mp_evidence_rows)} MP-evidence links")


def load_evidence(conn, df: pd.DataFrame):
    from psycopg2.extras import execute_values
    rows = []
    for _, r in df.iterrows():
        eid = to_int(r.get("evidence_id", ""))
        if eid is None:
            continue
        rows.append((
            eid,
            to_int(r.get("molecular_profile_id", "")),
            r.get("molecular_profile", ""),
            r.get("disease", ""),
            r.get("doid", ""),
            r.get("phenotypes", ""),
            r.get("therapies", ""),
            r.get("therapy_interaction_type", ""),
            r.get("evidence_type", ""),
            r.get("evidence_direction", ""),
            r.get("evidence_level", ""),
            r.get("significance", ""),
            r.get("evidence_statement", ""),
            r.get("citation_id", ""),
            r.get("source_type", ""),
            r.get("asco_abstract_id", ""),
            r.get("citation", ""),
            r.get("nct_ids", ""),
            to_int(r.get("rating", "")),
            r.get("evidence_status", ""),
            r.get("variant_origin", ""),
            to_timestamp(r.get("last_review_date", "")),
            r.get("evidence_civic_url", ""),
            r.get("molecular_profile_civic_url", ""),
            to_bool(r.get("is_flagged", "")),
            confidence_score(r.get("evidence_level", ""), r.get("rating", "")),
        ))

    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO evidence_items (
                evidence_id, molecular_profile_id, molecular_profile_name, disease, doid,
                phenotypes, therapies, therapy_interaction_type, evidence_type, evidence_direction,
                evidence_level, significance, evidence_statement, citation_id, source_type,
                asco_abstract_id, citation, nct_ids, rating, evidence_status, variant_origin,
                last_review_date, evidence_civic_url, molecular_profile_civic_url, is_flagged,
                confidence_score
            ) VALUES %s
            ON CONFLICT (evidence_id) DO UPDATE SET
                evidence_statement = EXCLUDED.evidence_statement,
                evidence_direction = EXCLUDED.evidence_direction,
                evidence_level = EXCLUDED.evidence_level,
                rating = EXCLUDED.rating,
                confidence_score = EXCLUDED.confidence_score,
                last_review_date = EXCLUDED.last_review_date
        """, rows)

    conn.commit()
    print(f"  loaded {len(rows)} evidence items")


def main():
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    try:
        print("Variants:")
        load_variants(conn, fetch_tsv(VARIANT_URL))

        print("Molecular profiles:")
        load_molecular_profiles(conn, fetch_tsv(MOLECULAR_PROFILE_URL))

        print("Evidence:")
        load_evidence(conn, fetch_tsv(EVIDENCE_URL))

        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())