"""Explicit public-document retrieval only; no KIS authentication or price-data requests."""

import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/km005r1"
    private = root / "data/km005r1-private-documents"
    private.mkdir(exist_ok=True)
    policy = "https://apiportal.koreainvestment.com/api/forums/10000000-0000-0011-0000-000000000002/posts/1f422ddb-7a9c-4279-9ecb-21eb750a4b7a"
    urls = {
        "KIS_CUSTOMER_TERMS": "https://apiportal.koreainvestment.com/api/terms/public?termsType=MARKET",
        "KIS_DATA_POLICY_20261006": policy,
        "KRX_TERMS": "https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp",
        "KRX_PURCHASE": "https://openapi.krx.co.kr/contents/OPP/DATA/OPPDATA001.jsp",
        "FNGUIDE_PRICE": "https://help-dataguide.fnguide.com/ko/articles/이용-및-요금-안내-48b18a4b",
        "FNGUIDE_COVERAGE": "https://help-dataguide.fnguide.com/ko/articles/제공-데이터-안내-5c5347da",
        "KOSCOM_HISTORY": "https://www.koscom.co.kr/mobile/main/contents.do?menuNo=400044",
    }
    from urllib.parse import quote

    proof = []
    for identity, url in urls.items():
        encoded = quote(url, safe=":/?=&%")
        request = urllib.request.Request(
            encoded, headers={"User-Agent": "kmast-public-document-audit"}
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("document size limit")
            (private / (identity + ".source")).write_bytes(body)
            record = dict(
                identity=identity,
                official_url=encoded,
                checked_at=datetime.now(UTC).isoformat(),
                response_sha256=hashlib.sha256(body).hexdigest(),
                body_obtained=True,
            )
            if identity.startswith("KIS_"):
                item = json.loads(body)
                item = item[0] if isinstance(item, list) else item
                record.update(
                    title=item.get("title", item.get("name")),
                    version=item.get("version"),
                    published_at=item.get("createdDate"),
                    modified_at=item.get("lastModifiedDate"),
                    content_sha256=hashlib.sha256(item["content"].encode()).hexdigest(),
                )
            proof.append(record)
        except Exception as error:
            proof.append(
                dict(
                    identity=identity,
                    official_url=encoded,
                    body_obtained=False,
                    error_category=type(error).__name__,
                )
            )
    assert all(p["body_obtained"] for p in proof if p["identity"].startswith("KIS_"))
    (output / "official-documents.json").write_bytes(
        json.dumps(proof, ensure_ascii=True, indent=2).encode()
    )
    print([(p["identity"], p["body_obtained"]) for p in proof])


if __name__ == "__main__":
    main()
