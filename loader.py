#!/usr/bin/env python3
"""
Simple Salesforce Data Loader

Features:
- Read CSV or Excel (.xlsx) via pandas
- Map columns using a JSON mapping file (input column -> SObject field API name)
- Authenticate to Salesforce using username+password+security token (simple-salesforce)
- Insert or upsert (using an external id field) in batches
- Log successes and failures to CSV files

Usage:
python loader.py --input sample.csv --mapping sample_mapping.json --object Account --operation upsert --external-id External_Id__c
"""
import argparse
import json
import os
import sys
import csv
from typing import Callable, Dict, List, Any, Optional
from dotenv import load_dotenv
import pandas as pd
from simple_salesforce import Salesforce, SalesforceMalformedRequest, SalesforceResourceNotFound, SalesforceGeneralError

BATCH_SIZE = 200  # safe batch size for REST API
ProgressCallback = Callable[[int, int], None]


def print_status(message: str) -> None:
    print(message, flush=True)


def format_progress(processed: int, total: int) -> str:
    if total <= 0:
        return "0/0 (100.0%)"
    percent = processed / total * 100
    return f"{processed}/{total} ({percent:.1f}%)"


def load_mapping(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_input(path: str, skip_header: bool = True) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in [".xls", ".xlsx"]:
        df = pd.read_excel(path, engine="openpyxl")
    elif ext == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported input file type: {ext}")
    return df


def row_to_sobject(row: pd.Series, mappings: Dict[str, str]) -> Dict[str, Any]:
    out = {}
    for col_name, sf_field in mappings.items():
        if col_name in row and not pd.isna(row[col_name]):
            out[sf_field] = row[col_name]
    return out


def chunked(iterable: List[Any], size: int):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def connect_salesforce() -> Salesforce:
    load_dotenv()
    username = os.getenv("SF_USERNAME")
    password = os.getenv("SF_PASSWORD")
    token = os.getenv("SF_SECURITY_TOKEN")
    domain = os.getenv("SF_DOMAIN", "login")  # 'login' or 'test'
    if not username or not password:
        raise RuntimeError("SF_USERNAME and SF_PASSWORD must be set in environment or .env file")
    try:
        sf = Salesforce(username=username, password=password, security_token=token or None, domain=domain)
        return sf
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Salesforce: {e}")


def perform_insert(
    sf: Salesforce,
    sobject_api: str,
    records: List[Dict[str, Any]],
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Dict[str, Any]]:
    results = []
    total = len(records)
    processed = 0
    for batch in chunked(records, BATCH_SIZE):
        try:
            res = sf.bulk.__getattr__(sobject_api).insert(batch) if hasattr(sf, "bulk") else [sf.__getattr__(sobject_api).create(r) for r in batch]
            # normalize result
            for r in res:
                results.append(r)
        except Exception as e:
            # fallback: try single creates to capture row errors
            for r in batch:
                try:
                    rec_res = sf.__getattr__(sobject_api).create(r)
                    results.append(rec_res)
                except Exception as e2:
                    results.append({"success": False, "errors": str(e2), "id": None})
        processed += len(batch)
        if progress_callback:
            progress_callback(processed, total)
    return results


def perform_upsert(
    sf: Salesforce,
    sobject_api: str,
    records: List[Dict[str, Any]],
    external_id_field: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[Dict[str, Any]]:
    results = []
    total = len(records)
    processed = 0
    for batch in chunked(records, BATCH_SIZE):
        for r in batch:
            try:
                res = sf.__getattr__(sobject_api).upsert(f"{external_id_field}/{r.get(external_id_field)}", r)
                results.append({"success": True, "id": res.get("id") if isinstance(res, dict) else res})
            except Exception as e:
                # try create if upsert failed due to missing external id
                try:
                    cr = sf.__getattr__(sobject_api).create(r)
                    results.append({"success": True, "id": cr.get("id")})
                except Exception as e2:
                    results.append({"success": False, "errors": str(e2), "id": None})
            processed += 1
            if progress_callback:
                progress_callback(processed, total)
    return results


def count_results(results: List[Dict[str, Any]]) -> Dict[str, int]:
    successes = 0
    failures = 0
    for res in results:
        if res.get("success") is True or (res.get("success") is None and res.get("id")):
            successes += 1
        else:
            failures += 1
    return {"successes": successes, "failures": failures}


def write_log(success_log_path: str, failure_log_path: str, rows: List[Dict[str, Any]], results: List[Dict[str, Any]]):
    # write two CSVs: successes and failures
    successes = []
    failures = []
    for row, res in zip(rows, results):
        out = {"id": res.get("id") if isinstance(res, dict) else None}
        out.update(row)
        if res.get("success") is True or res.get("success") is None and res.get("id"):
            successes.append(out)
        else:
            err = res.get("errors") or res
            row_copy = dict(row)
            row_copy["_error"] = err
            failures.append(row_copy)

    if successes:
        keys = list(successes[0].keys())
        with open(success_log_path, "w", newline="", encoding="utf-8") as sfh:
            writer = csv.DictWriter(sfh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(successes)
    if failures:
        keys = list(failures[0].keys())
        with open(failure_log_path, "w", newline="", encoding="utf-8") as ffh:
            writer = csv.DictWriter(ffh, fieldnames=keys)
            writer.writeheader()
            writer.writerows(failures)


def main():
    parser = argparse.ArgumentParser(description="Simple Salesforce Data Loader")
    parser.add_argument("--input", "-i", required=True, help="Input CSV or XLSX file")
    parser.add_argument("--mapping", "-m", required=True, help="JSON mapping file (input column -> SF field)")
    parser.add_argument("--object", "-o", required=True, help="Salesforce SObject API name (e.g., Account)")
    parser.add_argument("--operation", choices=["insert", "upsert"], default="insert", help="Operation to perform")
    parser.add_argument("--external-id", help="External ID field API name (required for upsert)")
    parser.add_argument("--skip-header", action="store_true", help="If set, treat first row as header and use mapping keys accordingly")
    parser.add_argument("--success-log", default="successes.csv", help="Path to success log CSV")
    parser.add_argument("--failure-log", default="failures.csv", help="Path to failure log CSV")
    args = parser.parse_args()

    print_status(f"Loading mapping from {args.mapping}...")
    mapping = load_mapping(args.mapping)
    mappings = mapping.get("mappings") if "mappings" in mapping else mapping
    options = mapping.get("options", {})

    print_status(f"Reading input from {args.input}...")
    df = read_input(args.input, skip_header=options.get("skip_header", True))
    if df.empty:
        print("No rows to process.")
        sys.exit(0)
    print_status(f"Prepared {len(df)} input rows.")

    # Normalize column names: mapping uses exact headers
    records = []
    original_rows = []
    for _, row in df.iterrows():
        srec = row_to_sobject(row, mappings)
        records.append(srec)
        original_rows.append(row.to_dict())

    print_status("Connecting to Salesforce...")
    sf = connect_salesforce()
    print_status("Connected to Salesforce.")

    def report_upload_progress(processed: int, total: int) -> None:
        print_status(f"Upload progress: {format_progress(processed, total)}")

    results = []
    if args.operation == "insert":
        print_status(f"Starting insert upload to {args.object} in batches of {BATCH_SIZE}...")
        results = perform_insert(sf, args.object, records, report_upload_progress)
    else:
        if not args.external_id:
            print("External id field is required for upsert operation.")
            sys.exit(1)
        print_status(f"Starting upsert upload to {args.object} using {args.external_id}...")
        results = perform_upsert(sf, args.object, records, args.external_id, report_upload_progress)

    write_log(args.success_log, args.failure_log, original_rows, results)
    counts = count_results(results)
    print_status(
        f"Done. {counts['successes']} succeeded, {counts['failures']} failed. "
        f"Successes written to {args.success_log}, failures to {args.failure_log}"
    )


if __name__ == "__main__":
    main()
