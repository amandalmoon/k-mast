"""Supplementary offline diagnostics; never repair or overwrite primary parsed evidence."""

import io
import json
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from kmast.data.document_relations import correction_relation
from kmast.data.panel_acquisition import atomic_json
from kmast.data.store import canonical, digest


def main():
    private = Path("data/data-first-private-df008-documents")
    target = json.loads(Path("artifacts/df008/document-targets.json").read_bytes())
    originals = [
        r
        for r in json.loads(
            Path("data/data-first-private-df007-census-v2/candidate-register.json").read_bytes()
        )
        if r["family"] == "D1"
    ]
    diagnostics = []
    for group in ("originals", "revisions"):
        for row in target[group]:
            cache = private / "cache" / (row["receipt"] + ".json")
            if not cache.exists():
                continue
            record = json.loads(cache.read_bytes())
            item = dict(
                receipt=row["receipt"],
                group=group,
                raw_sha256=record["sha256"],
                api_status=record["api_status"],
                parsed=False,
                xml_error_code=None,
                xml_error_position=None,
                explicit_stock_code_label=False,
                explicit_stock_code_tag=False,
                official_parent_link_candidates=[],
            )
            if record["success"]:
                archive = zipfile.ZipFile(
                    io.BytesIO((private / "wire" / (record["sha256"] + ".bin")).read_bytes())
                )
                # Primary qualification has already bounded expansion; use exact receipt member.
                name = row["receipt"] + ".xml"
                if name in archive.namelist():
                    raw = archive.read(name)
                    try:
                        root = ET.fromstring(raw)
                        item["parsed"] = True
                        text = "".join(root.itertext())
                        if group == "revisions":
                            item["official_relation"] = correction_relation(
                                text, row["receipt"], row["corp_code"], originals
                            )
                        item["explicit_stock_code_label"] = any(
                            label in text
                            for label in ("종목코드", "주식코드", "종목 코드", "주식 코드")
                        )
                        item["explicit_stock_code_tag"] = any(
                            e.tag.upper() in {"STOCK-CODE", "STOCK_CODE", "STOCKCODE"}
                            for e in root.iter()
                        )
                    except ET.ParseError as error:
                        item["xml_error_code"] = error.code
                        item["xml_error_position"] = error.position
                qualified = private / "qualified" / (row["receipt"] + ".json")
                if qualified.exists():
                    parsed = json.loads(qualified.read_bytes())
                    item["official_parent_link_candidates"] = parsed.get(
                        "correction_parent_candidates", []
                    )
            diagnostics.append(item)
    atomic_json(private / "identity-diagnostics.json", diagnostics)
    summary = dict(
        records=len(diagnostics),
        parsed=sum(r["parsed"] for r in diagnostics),
        explicit_stock_code_labels=sum(r["explicit_stock_code_label"] for r in diagnostics),
        explicit_stock_code_tags=sum(r["explicit_stock_code_tag"] for r in diagnostics),
        xml_error_codes=dict(
            Counter(
                str(r["xml_error_code"]) for r in diagnostics if r["xml_error_code"] is not None
            )
        ),
        parent_link_candidate_documents=sum(
            bool(r["official_parent_link_candidates"]) for r in diagnostics
        ),
        private_diagnostics_sha256=digest(canonical(diagnostics)),
        repair_applied=False,
        malformed_documents_remain_unknown=True,
        verified_correction_parent_links=sum(
            r.get("official_relation", {}).get("relation_verified") is True for r in diagnostics
        ),
    )
    atomic_json(Path("artifacts/df008/identity-diagnostics.json"), summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
