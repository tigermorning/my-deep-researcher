# -*- coding: utf-8 -*-
"""스위치를 하나씩 끈 설정 + 혼자 하는 대조군을 같은 질문으로 여러 번 돌려 지표를 모은다.

    PYTHONIOENCODING=utf-8 python ablation.py                       # 기본: 5문항 × 5설정 × 3회
    PYTHONIOENCODING=utf-8 python ablation.py --qs q03 q11 --reps 2
    PYTHONIOENCODING=utf-8 python ablation.py --collect             # 다시 돌리지 않고 output/ablation.json의 실행만 다시 집계

- 실행 하나 = 프로세스 하나(`graph.py --off …` / `baseline.py --budget …`). 비용 카운터가 전역이라 한 프로세스에서 섞지 않는다
- 스위치를 '껐다'는 것은 graph.py가 시작할 때 찍는 스위치 줄과, 실행 결과의 config에 남은 값으로 확인한다(로그만 바뀌는 사고 방지)
- 대조군 예산 = 같은 문항 '기본' 실행들이 실제로 읽은 청크 수의 평균. 그래서 기본을 먼저 다 돌린다
- 한 번 돌린 값으로 단정하지 않는다: 평균과 함께 최솟값~최댓값을 적는다
"""
import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIGS = {"기본": [], "배정검사끔": ["배정검사"], "남의구역끔": ["남의구역"], "재위임끔": ["재위임"]}
ALARMS = ["허위인용", "범위밖큐", "무근거절", "무효배정"]
KEYS = ["격리율", "중복률", "규정대조율", "트랙도달률", "읽고안쓴문서", "인용밀도", "인용문일치율", "인용문검사", "예산소진율",
        "재위임절", "되돌림", "읽은청크", "보고서글자", "호출", "재질문"]


def launch(cmd):
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable] + cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env)
    m = re.search(r"저장: output/reports/(.+)\.md", p.stdout)
    if not m:
        print(f"  실패: {' '.join(cmd)}\n{p.stdout[-800:]}\n{p.stderr[-1500:]}")
        return None
    name = m.group(1)
    row = json.loads((ROOT / "output" / "runs" / f"{name}.json").read_text(encoding="utf-8"))
    print(f"  끝: {name}  {row['metrics']['호출']}호출")
    return name


def load(name):
    return json.loads((ROOT / "output" / "runs" / f"{name}.json").read_text(encoding="utf-8"))


def recompute(names):
    """저장된 실행에서 지표만 다시 계산한다(API 호출 없음) — 지표를 추가·수정했을 때.
    COST는 저장된 값에서 되살린다. 보고서 전체 텍스트는 reports/*.md에서 읽는다."""
    import graph as g
    import metrics
    for n in names:
        r = load(n)
        m0 = r["metrics"]
        cost = {"calls": m0["호출"], "coord_chars": m0["코디네이터글자"], "sub_chars": m0["조사관글자"],
                "retry": m0.get("재질문", 0), "json_fail": m0.get("JSON실패", 0)}
        s = {"question": r["question"], "visited": r["visited"],
             "report": (ROOT / "output" / r["report_file"]).read_text(encoding="utf-8"),
             "plan": {**r["plan"], "채택": {str(x["번호"]): x for x in r["sections"]}}}
        r["metrics"] = metrics.compute(s, cost, g)
        (ROOT / "output" / "runs" / f"{n}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


def aggregate(names):
    rows, dropped = [], []
    for n in names:
        if not n:
            continue
        r = load(n)
        # 빈 결과를 정상 실행처럼 평균 내지 않는다: JSON이 끝내 깨진 실행·절이 0개인 실행은 뺀다(따로 센다)
        if r["metrics"].get("JSON실패") or r["metrics"]["절수"] == 0:
            dropped.append(n)
            continue
        rows.append(r)
    table = {"_제외": dropped}
    for r in rows:
        cell = table.setdefault(r["qid"], {}).setdefault(r["tag"], {"runs": [], "metrics": []})
        cell["runs"].append(r["run"])
        cell["metrics"].append(r["metrics"])
        if r["tag"] in CONFIGS:          # 스위치가 실제로 그 조합인지 결과에 남은 config로 확인(나머지는 켜져 있어야)
            want = {k: k not in CONFIGS[r["tag"]] for k in r["config"]["스위치"]}
            assert r["config"]["스위치"] == want, f"{r['run']}: 스위치 {r['config']['스위치']} != {want}"
        base_cfg = {k: v for k, v in r["config"].items() if k != "스위치"}
        assert base_cfg == {k: v for k, v in rows[0]["config"].items() if k != "스위치"}, f"{r['run']}: config가 다르다"
    for q, tags in table.items():
        if q.startswith("_"):
            continue
        for tag, cell in tags.items():
            ms = cell["metrics"]
            cell["요약"] = {}
            for k in KEYS:
                vs = [m[k] for m in ms if m.get(k) is not None]
                if vs:
                    cell["요약"][k] = {"평균": round(sum(vs) / len(vs), 1), "최소": min(vs), "최대": max(vs)}
            cell["경보실행"] = sum(1 for m in ms if any(m.get(a) for a in ALARMS))
            cell["경보합"] = {a: sum(m.get(a, 0) for m in ms) for a in ALARMS}
    return table


def markdown(table):
    tags = list(CONFIGS) + ["대조군"]
    out = []
    for q in sorted(k for k in table if not k.startswith("_")):
        out.append(f"\n### {q}\n")
        cols = [t for t in tags if t in table[q]]
        out.append("| 지표 | " + " | ".join(f"{t} (n={len(table[q][t]['runs'])})" for t in cols) + " |")
        out.append("|---|" + "---|" * len(cols))
        out.append("| 경보 난 실행 | " + " | ".join(f"{table[q][t]['경보실행']}" for t in cols) + " |")
        for a in ALARMS:
            out.append(f"| └ {a} 합 | " + " | ".join(f"{table[q][t]['경보합'][a]}" for t in cols) + " |")
        for k in KEYS:
            cells = []
            for t in cols:
                s = table[q][t]["요약"].get(k)
                cells.append(f"{s['평균']} ({s['최소']}~{s['최대']})" if s else "-")
            out.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--qs", nargs="+", default=["q01", "q03", "q07", "q10", "q11"])
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--recompute", action="store_true", help="--collect와 함께: 저장된 실행의 지표를 다시 계산")
    ap.add_argument("--replace", action="store_true", help="기존 ablation.json에서 --qs 문항의 실행만 새로 돌린 것으로 바꾼다")
    a = ap.parse_args()
    out_json = ROOT / "output" / "ablation.json"

    if a.collect:
        names = json.loads(out_json.read_text(encoding="utf-8"))["runs"]
        if a.recompute:
            recompute(names)
    else:
        jobs = [(q, tag, offs) for q in a.qs for tag, offs in CONFIGS.items() for _ in range(a.reps)]
        print(f"1단계: 팀 실행 {len(jobs)}개 (동시 {a.workers})")
        with ThreadPoolExecutor(a.workers) as ex:
            names = list(ex.map(lambda j: launch(["graph.py", j[0], "--tag", j[1]]
                                                 + (["--off", ",".join(j[2])] if j[2] else [])), jobs))
        budgets = {}
        for n in names:
            if n:
                r = load(n)
                if r["tag"] == "기본" and r["metrics"]["절수"] > 0:   # 받은 예산이 아니라 실제로 읽은 청크 수 — 팀이 일찍 멈춘 만큼 대조군도 덜 받는다
                    budgets.setdefault(r["qid"], []).append(len(r["visited"]))
        base_jobs = [(q, round(sum(budgets[q]) / len(budgets[q]))) for q in a.qs if q in budgets for _ in range(a.reps)]
        print(f"2단계: 대조군 {len(base_jobs)}개 — 예산 {({q: b for q, b in base_jobs})}")
        with ThreadPoolExecutor(a.workers) as ex:
            names += list(ex.map(lambda j: launch(["baseline.py", j[0], "--budget", str(j[1])]), base_jobs))
    if a.replace and not a.collect and out_json.exists():
        old = json.loads(out_json.read_text(encoding="utf-8"))["runs"]
        names = [n for n in old if load(n)["qid"] not in a.qs] + names
    table = aggregate(names)
    out_json.write_text(json.dumps({"runs": [n for n in names if n], "table": table}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    md = markdown(table)
    (ROOT / "output" / "ablation.md").write_text("# 절제 실험 결과 (자동 생성)\n\n평균 (최소~최대). 경보는 0이어야 정상.\n" + md,
                                              encoding="utf-8")
    print(md)
    print(f"실패한 실행: {sum(1 for n in names if not n)} · 집계에서 뺀 실행: {len(table['_제외'])}")


if __name__ == "__main__":
    main()
