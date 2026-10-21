"""표준 라이브러리 BM25: 한국어 단어·문자 2-gram으로 문단 검색. 임베딩 미사용."""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

MANUAL_DIR = Path(__file__).resolve().parent.parent / "data" / "iot_manuals"
POLICY_DIR = MANUAL_DIR.parent / "iot_policies"
SOURCE_FIELDS = ("source_type", "publisher", "source_url", "source_title", "source_section",
                 "retrieved_at", "applicable_models")
OFFICIAL_HOSTS = {"kb.shelly.cloud", "shelly-api-docs.shelly.cloud"}


def source_description(document):
    """검색·진단 답변에서 동일한 출처 표시를 사용한다."""
    if document.get("source_type") == "manufacturer_summary":
        return (f"제조사 문서 기반 요약 · {document['publisher']} · {document['source_section']}"
                f" · 확인 {document['retrieved_at']}\n원문: {document['source_url']}")
    return "프로젝트 가상 복구 정책 · 제조사 기능이 아닙니다."

STOP = {"점검", "장치", "센서", "방법", "주세요", "알려", "문제", "확인", "해줘", "해줘요"}
EXPANSIONS = {"안와": "수신 지연", "안와요": "수신 지연", "안들어": "수신 지연", "멈췄": "수집 중단",
              "꺼졌": "오프라인 연결", "방전": "배터리 전원", "잠자": "절전 기상",
              "telemetry_delayed": "데이터 수신 지연", "low_battery": "배터리 잔량 전원",
              "offline": "오프라인 연결 통신", "sleeping": "정상 절전 기상", "healthy": "정상 주기 관측",
              "invalid_data": "관측 데이터 누락 형식"}


def tokenize(text):
    words = re.findall(r"[a-z0-9_]+|[가-힣]+", text.lower())
    out = []
    for word in words:
        if word in STOP or word.isdigit():
            continue
        out.append(word)
        if re.fullmatch(r"[가-힣]{3,}", word):
            out.extend(word[i:i+2] for i in range(len(word)-1))
    return out


class ManualIndex:
    def __init__(self, directory=MANUAL_DIR):
        self.chunks = []
        digest = hashlib.sha256()
        folders = [Path(directory)]
        if Path(directory).resolve() == MANUAL_DIR.resolve():
            folders.append(POLICY_DIR)
        paths = sorted(path for folder in folders for path in folder.glob("*.md"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            digest.update(path.parent.name.encode() + path.name.encode() + text.encode())
            match = re.search(r"<!-- meta: (.*?) -->", text)
            if not match:
                continue
            meta = json.loads(match.group(1))
            if meta.get("source_type") == "manufacturer_summary":
                from urllib.parse import urlparse
                url = urlparse(meta.get("source_url", ""))
                if (url.scheme != "https" or url.hostname not in OFFICIAL_HOSTS
                    or not all(meta.get(key) for key in SOURCE_FIELDS)):
                    raise ValueError(f"공식 문서 출처 정보가 불완전합니다: {path.name}")
            parts = re.split(r"^## (.+)$", text, flags=re.M)
            for number, (heading, body) in enumerate(zip(parts[1::2], parts[2::2]), 1):
                causes = [{**c, "source_id": f"{meta['id']}#{number}"} for c in meta.get("causes", [])]
                self.chunks.append({"source_id": f"{meta['id']}#{number}", "document_id": meta["id"],
                    "filename": path.name, "title": meta["title"], "section": heading,
                    "text": body.strip(), "issues": meta["issues"], "tags": meta["tags"],
                    "causes": causes, "origin": meta["origin"], "version": meta["version"],
                    "power_sources": meta.get("section_power_sources", {}).get(str(number), []),
                    **{key: meta.get(key) for key in SOURCE_FIELDS}})
        self.version = digest.hexdigest()[:12]
        self.counts = [Counter(tokenize(" ".join([c['title'], c['section'], c['text'], *c['tags'], *c['issues']]))) for c in self.chunks]
        self.df = Counter(t for counts in self.counts for t in counts)
        self.avg_length = sum(map(lambda c: sum(c.values()), self.counts)) / max(len(self.counts), 1)

    def search(self, query, *, issues=None, operating_state=None, top_k=3, model=None, power_source=None):
        if power_source is None:
            battery_query, usb_query = "배터리" in query, "usb" in query.lower()
            if battery_query != usb_query:
                power_source = "battery" if battery_query else "usb"
        expanded = query.lower()
        for key, value in EXPANSIONS.items():
            if key in expanded:
                expanded += " " + value
        terms = set(tokenize(expanded))
        allowed = None if issues is None else set(issues or (["sleeping"] if operating_state == "sleeping" else ["healthy"]))
        if allowed is not None and operating_state == "sleeping":
            allowed.add("sleeping")
        ranked = []
        for chunk, counts in zip(self.chunks, self.counts):
            if power_source is not None and chunk["power_sources"] and power_source not in chunk["power_sources"]:
                continue
            if model is not None and chunk.get("applicable_models") and model not in chunk["applicable_models"]:
                continue
            if allowed is not None and not allowed.intersection(chunk["issues"]):
                continue
            length = sum(counts.values())
            score = 0.0
            for term in terms:
                freq = counts.get(term, 0)
                if freq:
                    idf = math.log(1 + (len(self.chunks) - self.df[term] + .5) / (self.df[term] + .5))
                    score += idf * freq * 2.5 / (freq + 1.5 * (.25 + .75 * length / (self.avg_length or 1)))
            if score > 1:
                ranked.append({**chunk, "score": round(score, 4)})
        ranked.sort(key=lambda c: (-c["score"], c["source_id"]))
        selected, seen = [], set()
        for chunk in ranked:
            if chunk["document_id"] not in seen:
                selected.append(chunk)
                seen.add(chunk["document_id"])
            if len(selected) >= max(1, min(top_k, 5)):
                break
        return {"method": "bm25-ko-bigram", "index_version": self.version,
                "document_count": len({c['document_id'] for c in self.chunks}),
                "chunk_count": len(self.chunks),
                "manufacturer_document_count": len({c["document_id"] for c in self.chunks if c.get("source_type") == "manufacturer_summary"}),
                "policy_document_count": len({c["document_id"] for c in self.chunks if c.get("source_type") == "project_policy"}),
                "query": query, "documents": selected}
