# DF009 official KRX source assessment

The official portal's [service list](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd) documents historical coverage from 2010-01-04 for the four relevant services. That is a provider documentation claim; this run has not obtained a successful historical response.

The public pages rendered in the browser and their development specifications were downloaded without login, sample API calls or a sample key. A direct terminal request to the public HTML had returned 403; this is distinct from the actual data API's subsequent 401. Original DOCX files remain private, with hashes in `artifacts/df009/source-assessment.json`.

| Official service | API ID | Production path, host `data-dbg.krx.co.kr` |
|---|---|---|
| [KOSPI basics](https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=PiwgMdTwmsenXhmqqxuj) | stk_isu_base_info | /svc/apis/sto/stk_isu_base_info |
| [KOSDAQ basics](https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=CifLHplnUFMgpHIMMPXs) | ksq_isu_base_info | /svc/apis/sto/ksq_isu_base_info |
| [KOSPI daily trading](https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=JvJFzlAENzZlPBDNGAWC) | stk_bydd_trd | /svc/apis/sto/stk_bydd_trd |
| [KOSDAQ daily trading](https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=hZjGpkllgCBCWqeTsYFj) | ksq_bydd_trd | /svc/apis/sto/ksq_bydd_trd |

Production paths came from the downloaded official specifications, not by removing `sample` from an example URL. The portal shows modification date 2026-01-16; no semantic version is asserted. The document hashes identify the inspected contract versions. Both basics specifications declare input `basDd` and `OutBlock_1`, including `ISU_CD`, `ISU_SRT_CD`, `ISU_NM`, `ISU_ABBRV`, `LIST_DD`, `MKT_TP_NM`, `SECUGRP_NM`, and `KIND_STKCERT_TP_NM`. They do not themselves supply a DART corporate-ID field. A standard code and a short code must not be interchanged. Basics output also lacks a documented row-level BAS_DD echo: request/response provenance and historical semantics need separate evidence. Daily trading fields differ; no daily price endpoint was called.

[Official usage steps](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp) distinguish key approval from per-service approval. The [operating limit](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp) is at most 10,000 requests per key per day, subject to service restrictions. The pilot's stricter 46-query/92-attempt bound and 3.10-second completion wait do not override any provider restriction.

Actual probe: GET KOSPI basics, basDd 20221226, AUTH_KEY header from the user's local file. HTTP 401, provider code 401, reason `Unauthorized API Call`. It consumed one request and triggered a durable halt. No KOSDAQ data request, authentication issuance, automatic auth retry or date-availability inference followed. The generic response cannot distinguish invalid/expired key, key activation and individual service access. The user has been asked to verify those conditions; no key value is needed in chat.
