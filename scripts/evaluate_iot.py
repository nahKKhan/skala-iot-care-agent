"""고정 IoT 사례의 규칙·검색 평가와 선택적인 실제 Ollama 평가. 정답은 모델에 전달하지 않는다."""
import argparse
import hashlib
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_VERSION = hashlib.sha256(b"".join((ROOT / name).read_bytes() for name in ["agent/iot_graph.py", "agent/iot_llm.py", "agent/answer_quality.py", "agent/manual_search.py", "agent/device_rules.py", "agent/deps.py", "agent/mcp_client.py", "mcp_server.py", "agent/iot_simulator.py", "agent/device_logs.py", "agent/openai_llm.py", "agent/ollama_llm.py"])).hexdigest()[:12]
sys.path.insert(0, str(ROOT))
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
from agent.deps import IoTDeps
from agent.iot_graph import build_graph
from agent.fake_llm import RuleBasedLLM
from agent.ollama_llm import OllamaQualityLLM
from agent.mcp_client import MCPClient
from agent.session_store import SqliteSessionStore
from agent.iot_simulator import IoTSimulator


def legacy_issues(data):
    issues=[]
    if data["battery_pct"] <= 20:
        issues.append("low_battery")
    if not data["connected"]:
        issues.append("offline")
    elif data["telemetry_age_seconds"] > data["report_interval_seconds"] * 3:
        issues.append("telemetry_delayed")
    return issues


def write_report(report, output):
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cases=report["cases"]
    assessed=[c for c in cases if c["expected_issues"] is not None]
    requested=[c for c in cases if c["attempts"]]
    required=sum(len(c["required_documents"]) for c in cases)
    lines=["# IoT 진단·검색 평가 결과", "", f"- 실행: {report['created_at']}",
           f"- 모드: {report['backend']} / 모델: {report['model']}",
           f"- 파이프라인 코드 버전: {report.get('pipeline_version', '초기 평가에는 기록하지 않음')}",
           f"- 데이터: 고정된 가상 사례 {len(cases)}개. 실제 현장 성능으로 일반화할 수 없음.",
           "- 기준선: 변경 전 배터리·연결·지연 규칙과 수신 지연 매뉴얼 1개 고정 조회. 기준선 LLM 답변은 생성하지 않음.",
           "- 정답 분류와 필수 문서 목록은 평가기만 읽으며 모델 입력에 전달하지 않음.", "", "| 지표 | 기준선 | 개선 후 |", "|---|---:|---:|"]
    lines += [f"| 상태 분류 정답 사례 | {sum(c['baseline_classification_correct'] for c in assessed)}/{len(assessed)} | {sum(c['classification_correct'] for c in assessed)}/{len(assessed)} |",
              f"| 필수 문서 검색 포함 수 | {sum(c['baseline_document_hits'] for c in cases)}/{required} | {sum(c['document_hits'] for c in cases)}/{required} |",
              f"| 모델 호출 대상 중 검수 통과 답변 | 측정 안 함 | {sum(c['answer_source']=='llm' for c in requested)}/{len(requested)} |",
              f"| 채팅 중 복구 명령 미실행 | 측정 안 함 | {sum(c['no_command_executed'] for c in cases)}/{len(cases)} |", "",
              "검수 통과는 출처 ID·허용 후보·수치·조치 정책 및 일부 단정 표현 검사 결과다. 문장 의미 전체의 정확도를 뜻하지 않는다.",
              "실제 답변의 사실성·원인 단정·조치 적절성은 JSON의 manual_review 항목으로 별도 검토한다. 미검토 항목은 null이다.", "",
              "| 사례 | 입력 | 결과 출처 | 시간(초) | 검색 문서 | 검수 |", "|---|---|---|---:|---|---|"]
    for c in cases:
        lines.append(f"| {c['id']} | {c['query']} | {c['answer_source']} | {c['elapsed_seconds']} | {', '.join(c['retrieved_documents']) or '-'} | {c['qa'].get('passed') if c['qa'] else '-'} |")
    lines += ["", "## 검토 메모", "", "- 실제 기기·제조사 매뉴얼·현장 로그는 연결하지 않았다.",
              "- 소규모 개발용 평가 세트다. 독립된 대규모 검증 세트나 사람의 승인 결과가 아니다.",
              "- 실패 또는 규칙 기반 대체 답변도 그대로 기록하며 실제 모델 성능으로 성공 처리하지 않는다."]
    for c in cases:
        if c.get("review_note"):
            lines.append(f"- {c['id']}: {c['review_note']}")
    output.with_suffix(".md").write_text("\n".join(lines)+"\n",encoding="utf-8")


async def evaluate(args):
    cases=json.loads((ROOT/"data/evaluation_cases.json").read_text())[:args.limit]
    seed=IoTSimulator()
    results=[]
    with tempfile.TemporaryDirectory() as folder:
        store=SqliteSessionStore(Path(folder)/"evaluation.db")
        mcp=MCPClient(extra_env={"IOT_DB_PATH":str(store.db_path)})
        await mcp.start()
        try:
            model=OllamaQualityLLM(args.model) if args.backend=="ollama" else RuleBasedLLM("rules-evaluation")
            graph=build_graph(IoTDeps(quality_llm=model,mcp=mcp,session_store=store))
            for case in cases:
                start=time.monotonic()
                result=await graph.ainvoke({"query":case["query"]})
                elapsed=round(time.monotonic()-start,2)
                expected=case["expected_issues"]
                original=seed.status(case["device_id"]) if case["device_id"] else {"ok":False}
                previous=legacy_issues(original["data"]) if original["ok"] else None
                current=result.get("assessment",{}).get("issues")
                retrieved=[d["document_id"] for d in result.get("retrieval",{}).get("documents",[])]
                fixed=["telemetry_delayed"] if previous and "telemetry_delayed" in previous else []
                required=set(case["required_documents"])
                if original["ok"]:
                    after=await mcp.call_tool("get_device_status",{"device_id":case["device_id"]})
                    no_command=after["data"]["recovery_attempts"]==0 and after["data"]["telemetry_sequence"]==0
                else:
                    no_command=True
                results.append({**case,"classification_correct":current==expected if expected is not None else case["expected_text"] in result["final"],
                    "baseline_classification_correct":previous==expected if expected is not None else None,
                    "baseline_document_hits":len(required.intersection(fixed)),"document_hits":len(required.intersection(retrieved)),
                    "retrieved_documents":retrieved,"sources":result.get("retrieval",{}),"no_command_executed":no_command,
                    "answer_source":result.get("answer_source","rules"),"qa":result.get("qa"),"attempts":result.get("attempts",0),
                    "llm_usage":result.get("llm_usage"),"elapsed_seconds":elapsed,"draft":result.get("draft"),"reply":result["final"],
                    "manual_review":{"factuality":None,"uncertain_causes":None,"appropriate_actions":None}})
                print(f"{case['id']} {results[-1]['answer_source']} {elapsed}s",flush=True)
        finally:
            await mcp.stop()
            store.close()
    report={"pipeline_version":PIPELINE_VERSION,"created_at":datetime.now().astimezone().isoformat(timespec="seconds"),"backend":args.backend,"model":args.model if args.backend=="ollama" else "none","cases":results}
    write_report(report,args.output)
    print("report:",args.output,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--backend",choices=["rules","ollama"],default="rules")
    parser.add_argument("--model",default="qwen3.5:2b")
    parser.add_argument("--limit",type=int,default=12)
    parser.add_argument("--output",type=Path,default=ROOT/"doc/evaluation_rules.json")
    parser.add_argument("--render-only",type=Path)
    args=parser.parse_args()
    if args.render_only:
        write_report(json.loads(args.render_only.read_text()),args.render_only)
    else:
        asyncio.run(evaluate(args))
