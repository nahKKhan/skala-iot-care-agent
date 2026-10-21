"""표준 라이브러리 BM25: 한국어 단어·문자 2-gram으로 문단 검색. 임베딩 미사용."""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

MANUAL_DIR = Path(__file__).resolve().parent.parent / "data" / "iot_manuals"
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
        for path in sorted(Path(directory).glob("*.md")):
            text = path.read_text(encoding="utf-8")
            digest.update(path.name.encode() + text.encode())
            match = re.search(r"<!-- meta: (.*?) -->", text)
            if not match:
                continue
            meta = json.loads(match.group(1))
            parts = re.split(r"^## (.+)$", text, flags=re.M)
            for number, (heading, body) in enumerate(zip(parts[1::2], parts[2::2]), 1):
                causes = [{**c, "source_id": f"{meta['id']}#{number}"} for c in meta.get("causes", [])]
                self.chunks.append({"source_id": f"{meta['id']}#{number}", "document_id": meta["id"],
                    "filename": path.name, "title": meta["title"], "section": heading,
                    "text": body.strip(), "issues": meta["issues"], "tags": meta["tags"],
                    "causes": causes, "origin": meta["origin"], "version": meta["version"]})
        self.version = digest.hexdigest()[:12]
        self.counts = [Counter(tokenize(" ".join([c['title'], c['section'], c['text'], *c['tags'], *c['issues']]))) for c in self.chunks]
        self.df = Counter(t for counts in self.counts for t in counts)
        self.avg_length = sum(map(lambda c: sum(c.values()), self.counts)) / max(len(self.counts), 1)

    def search(self, query, *, issues=None, operating_state=None, top_k=3):
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
                "chunk_count": len(self.chunks), "query": query, "documents": selected}
