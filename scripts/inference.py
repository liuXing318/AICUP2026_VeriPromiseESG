"""
ESG 永續承諾驗證 — Zero/Few-shot 推論管線
透過 SSH tunnel 連到 DGX Spark 上的 LiteLLM，用 GPT-OSS-20B 做分類。
並行處理：ThreadPoolExecutor 同時發送多個 API 請求。
"""

import argparse
import os
import time
import sys
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from tqdm import tqdm
from dotenv import load_dotenv
from openai import OpenAI
from sshtunnel import SSHTunnelForwarder

load_dotenv()


# ---------------------------------------------------------------------------
# System prompt（完整版，來自 esg_strategy.md）
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是一位 ESG 永續報告分析專家，負責從企業永續報告書段落中標註承諾與證據資訊。

請嚴格依序完成以下標註，並嚴格按照指定格式輸出結果。

【標註定義】

1. promise_status（承諾狀態）
承諾是指與 ESG 準則相關的陳述，包含企業的原則(principle)、承諾(commitment)或策略(strategy)，無論是已實行、進行中或未來規劃。僅陳述客觀事實、報告數據、引用第三方評語或描述評估方法論，不算承諾。
- Yes：文本包含承諾
- No：文本不包含承諾

2. promise_string（承諾語句）
若承諾狀態為 Yes，從文本中摘錄與承諾相關的語句。若有多段不連續的語句，以「 ｜ 」連接。若承諾狀態為 No，輸出「（無）」。

3. evidence_status（證據狀態）
證據是指與承諾最相關的支持資訊，包含但不限於具體案例、企業措施、數據等。
- Yes：文本包含支持承諾的證據
- No：文本不包含支持承諾的證據
- N/A：承諾狀態為 No 時選用

4. evidence_string（證據語句）
若證據狀態為 Yes，從文本中摘錄與證據相關的語句。若有多段，以「 ｜ 」連接。若證據狀態為 No 或 N/A，輸出「（無）」。

5. verification_timeline（驗證時間軸）
評估承諾的最終結果何時可被合理觀察與驗證（以西元 2024 年為基準）：
- already：承諾已實行，可於當期驗證
- within_2_years：2 年內可驗證（通常文本明確提到 2025 或 2026 年目標）
- between_2_and_5_years：2-5 年內可驗證，或承諾未明示具體目標完成年份時選用 (注意!承諾未明示具體目標完成年份時也是屬於此項!)
- more_than_5_years：5 年以上可驗證（通常涉及 2030 年以後的目標）
- N/A：承諾狀態為 No 時選用

6. evidence_quality（證據品質）
根據你在上方摘錄的承諾語句與證據語句，評估證據語意的清晰度與精確度：
- Clear：資訊充分，內容清晰且合乎邏輯，與承諾有關聯
- Not Clear：資訊不足，內容僅部分可理解或過於表面，使用如「持續推進」「努力改善」等模糊字眼
- Misleading：證據與承諾之間無明確關聯，可能轉移注意力或造成誤解
- N/A：承諾或證據狀態為 No 時選用

【輸出格式】
請嚴格按照以下格式，每行一個欄位，不要輸出任何其他內容。
注意：先判斷狀態，再摘錄語句。

promise_status: <Yes/No>
promise_string: <承諾核心語句或（無）>
evidence_status: <Yes/No/N/A>
evidence_string: <證據核心語句或（無）>
verification_timeline: <already/within_2_years/between_2_and_5_years/more_than_5_years/N/A>
evidence_quality: <Clear/Not Clear/Misleading/N/A>"""


# ---------------------------------------------------------------------------
# Few-shot examples（5 個：1 No + 4 Yes 覆蓋不同組合）
# ---------------------------------------------------------------------------
FEW_SHOT = [
    # 1) promise=No — 純事實/數據陳述
    {
        "text": "目前主管機關規畫碳費每噸 300 元。公司經自主減碳計畫等申請相關優惠措施，每噸碳費降至 50 元。",
        "response": "promise_status: No\npromise_string: （無）\nevidence_status: N/A\nevidence_string: （無）\nverification_timeline: N/A\nevidence_quality: N/A",
    },
    # 2) promise=Yes, evidence=Yes, quality=Clear, timeline=already
    {
        "text": "資安團隊亦會不定期參與客戶或資安廠商所舉辦的情報分享或技術研討會共計 52 人次，不斷提升資安團隊之知識與技能。",
        "response": "promise_status: Yes\npromise_string: 不斷提升資安團隊之知識與技能\nevidence_status: Yes\nevidence_string: 參與情報分享或技術研討會共計52人次\nverification_timeline: already\nevidence_quality: Clear",
    },
    # 3) promise=Yes, evidence=Yes, quality=Not Clear, timeline=between_2_and_5_years
    {
        "text": "在與供應商攜手邁向永續發展的過程中，台泥致力於建立一套以合作為基礎的價值體體系。核心原則是推動供應鏈的低碳轉型，同時維護人權、保護環境和促進生物多樣性，以建立永續的合作夥伴關係。",
        "response": "promise_status: Yes\npromise_string: 台泥致力於建立以合作為基礎的價值體系\nevidence_status: Yes\nevidence_string: 推動供應鏈低碳轉型，維護人權保護環境\nverification_timeline: between_2_and_5_years\nevidence_quality: Not Clear",
    },
    # 4) promise=Yes, evidence=No, quality=N/A, timeline=already
    {
        "text": "與客戶密切合作，定期以會議／問卷方式了解並回應客戶的需求及聲音，提供最佳客戶服務。",
        "response": "promise_status: Yes\npromise_string: 與客戶密切合作，提供最佳客戶服務\nevidence_status: No\nevidence_string: （無）\nverification_timeline: already\nevidence_quality: N/A",
    },
    # 5) promise=Yes, evidence=Yes, quality=Clear, timeline=more_than_5_years
    {
        "text": "台達持續訂定及推動內外部氣候變遷目標，2021 年承諾 2030 年全球達成 RE100、2022 年通過科學減碳目標倡議組織 (SBTi) 的淨零科學減碳目標審核。",
        "response": "promise_status: Yes\npromise_string: 承諾2030年全球達成RE100\nevidence_status: Yes\nevidence_string: 通過SBTi淨零科學減碳目標審核\nverification_timeline: more_than_5_years\nevidence_quality: Clear",
    },
]


# ---------------------------------------------------------------------------
# 合法值域
# ---------------------------------------------------------------------------
VALID_PROMISE = {"Yes", "No"}
VALID_EVIDENCE = {"Yes", "No", "N/A"}
VALID_QUALITY = {"Clear", "Not Clear", "Misleading", "N/A"}
VALID_TIMELINE = {"already", "within_2_years", "between_2_and_5_years",
                  "more_than_5_years", "N/A"}


# ---------------------------------------------------------------------------
# Prompt 建構
# ---------------------------------------------------------------------------
def build_messages(text: str) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex in FEW_SHOT:
        messages.append({"role": "user", "content": f"以下是一段企業永續報告書的文本，請進行標註：\n\n{ex['text']}"})
        messages.append({"role": "assistant", "content": ex["response"]})
    messages.append({"role": "user", "content": f"以下是一段企業永續報告書的文本，請進行標註：\n\n{text}"})
    return messages


# ---------------------------------------------------------------------------
# 輸出解析
# ---------------------------------------------------------------------------
def parse_response(text: str) -> dict:
    result = {
        "promise_status": None,
        "evidence_status": None,
        "evidence_quality": None,
        "verification_timeline": None,
    }

    if not text:
        return result

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        for key in result:
            if line.startswith(key + ":"):
                result[key] = line.split(":", 1)[1].strip()
                break

    return result


# ---------------------------------------------------------------------------
# 後處理硬規則
# ---------------------------------------------------------------------------
def post_process(parsed: dict) -> dict:
    p = parsed.copy()

    if p["promise_status"] not in VALID_PROMISE:
        p["promise_status"] = "No"
    if p["evidence_status"] not in VALID_EVIDENCE:
        p["evidence_status"] = "N/A"
    if p["evidence_quality"] not in VALID_QUALITY:
        p["evidence_quality"] = "N/A"
    if p["verification_timeline"] not in VALID_TIMELINE:
        p["verification_timeline"] = "N/A"

    # promise=No → 全 N/A
    if p["promise_status"] == "No":
        p["evidence_status"] = "N/A"
        p["evidence_quality"] = "N/A"
        p["verification_timeline"] = "N/A"

    # promise=Yes 但 evidence/timeline 是 N/A → 修正
    if p["promise_status"] == "Yes":
        if p["evidence_status"] == "N/A":
            p["evidence_status"] = "No"
        if p["verification_timeline"] == "N/A":
            p["verification_timeline"] = "between_2_and_5_years"

    # evidence=No 或 N/A → quality=N/A
    if p["evidence_status"] in ("No", "N/A"):
        p["evidence_quality"] = "N/A"

    return p


# ---------------------------------------------------------------------------
# 單筆推論
# ---------------------------------------------------------------------------
FALLBACK = {
    "promise_status": "No",
    "evidence_status": "N/A",
    "evidence_quality": "N/A",
    "verification_timeline": "N/A",
}


def infer_one(client: OpenAI, text: str, model: str, max_retries: int = 3) -> dict:
    messages = build_messages(text)

    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content

            if raw is None:
                simple_msgs = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"以下是一段企業永續報告書的文本，請進行標註：\n\n{text}"},
                ]
                resp2 = client.chat.completions.create(
                    model=model, messages=simple_msgs,
                    temperature=0, max_tokens=4096,
                )
                raw = resp2.choices[0].message.content

            if raw is None:
                return FALLBACK.copy()

            parsed = parse_response(raw)
            return post_process(parsed)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [WARN] 推論失敗，使用 fallback: {e}", file=sys.stderr)
                return FALLBACK.copy()


# ---------------------------------------------------------------------------
# 定期存檔
# ---------------------------------------------------------------------------
def save_checkpoint(df_rows, results, output_path):
    out_rows = []
    for seq_idx, (_, row) in enumerate(df_rows):
        pred = results[seq_idx]
        if pred is None:
            continue
        out_rows.append({
            "id": row["id"],
            "promise_status": pred["promise_status"],
            "verification_timeline": pred["verification_timeline"],
            "evidence_status": pred["evidence_status"],
            "evidence_quality": pred["evidence_quality"],
        })
    if out_rows:
        out_df = pd.DataFrame(out_rows)
        out_df.to_csv(output_path, index=False, encoding="utf-8",
                      lineterminator="\n")
    return len(out_rows)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="ESG 永續承諾 Zero/Few-shot 推論")
    parser.add_argument("--input", required=True, help="輸入 CSV 路徑")
    parser.add_argument("--output", required=True, help="輸出 CSV 路徑")
    parser.add_argument("--workers", type=int, default=4, help="並行 worker 數")
    parser.add_argument("--sample", type=int, default=0, help="只跑前 N 筆（0=全跑）")
    parser.add_argument("--model", default="gpt-oss-20b", help="模型名稱")
    parser.add_argument("--local-port", type=int, default=8080, help="本機轉發 port")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="不建立 SSH tunnel（假設已有）")
    parser.add_argument("--resume", action="store_true",
                        help="從已有的 output 檔續跑，跳過已完成的 ID")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    if args.sample > 0:
        df = df.head(args.sample)
    print(f"載入 {len(df)} 筆資料")

    done_ids = set()
    done_rows = []
    if args.resume and os.path.exists(args.output):
        prev = pd.read_csv(args.output)
        done_ids = set(prev["id"].tolist())
        done_rows = prev.to_dict("records")
        print(f"續跑模式：已有 {len(done_ids)} 筆，剩餘 {len(df) - len(done_ids)} 筆")

    todo = [(seq_idx, row) for seq_idx, (_, row) in enumerate(df.iterrows())
            if row["id"] not in done_ids]

    if not todo:
        print("所有資料都已完成！")
        return

    tunnel = None
    if not args.no_tunnel:
        print("建立 SSH tunnel...")
        missing = [k for k in ("DGX_SSH_HOST", "DGX_SSH_USER", "DGX_SSH_PASSWORD")
                   if not os.environ.get(k)]
        if missing:
            print(f"錯誤：請在 .env 設定 {', '.join(missing)}（參考 .env.example），"
                  "或改用 --no-tunnel", file=sys.stderr)
            sys.exit(1)
        tunnel = SSHTunnelForwarder(
            (os.environ["DGX_SSH_HOST"], int(os.environ.get("DGX_SSH_PORT", 22))),
            ssh_username=os.environ["DGX_SSH_USER"],
            ssh_password=os.environ["DGX_SSH_PASSWORD"],
            remote_bind_address=("127.0.0.1", int(os.environ.get("DGX_REMOTE_PORT", 4000))),
            local_bind_address=("127.0.0.1", args.local_port),
            set_keepalive=30,
        )
        tunnel.start()
        print(f"SSH tunnel 已建立: localhost:{args.local_port} → DGX:4000")

    try:
        client = OpenAI(
            base_url=f"http://localhost:{args.local_port}",
            api_key="dummy",
            timeout=180,
        )

        print("測試 API 連線...")
        t0 = time.time()
        test_result = infer_one(client, "測試文本", args.model)
        t1 = time.time()
        print(f"API 可用，單筆耗時: {t1 - t0:.1f}s，測試結果: {test_result}")

        results = [None] * len(df)
        lock = Lock()
        completed = [0]
        checkpoint_interval = 50
        pbar = tqdm(total=len(todo), desc="推論中")

        rows_list = list(df.iterrows())

        def worker(seq_idx, row):
            pred = infer_one(client, row["data"], args.model)
            with lock:
                results[seq_idx] = pred
                completed[0] += 1
                pbar.update(1)
                if completed[0] % checkpoint_interval == 0:
                    n = save_checkpoint(rows_list, results, args.output + ".partial")
                    pbar.write(f"  [checkpoint] 已存 {n} 筆新結果 → {args.output}.partial")

        print(f"開始推論（{args.workers} 並行 workers，每 {checkpoint_interval} 筆存檔）...")
        start = time.time()

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = []
            for seq_idx, row in todo:
                futures.append(executor.submit(worker, seq_idx, row))
            for f in as_completed(futures):
                f.result()

        pbar.close()
        elapsed = time.time() - start
        print(f"推論完成: {len(todo)} 筆，耗時 {elapsed:.0f}s "
              f"({elapsed/len(todo):.1f}s/筆)")

        new_rows = []
        for seq_idx, (_, row) in enumerate(rows_list):
            pred = results[seq_idx]
            if pred is None:
                continue
            new_rows.append({
                "id": row["id"],
                "promise_status": pred["promise_status"],
                "verification_timeline": pred["verification_timeline"],
                "evidence_status": pred["evidence_status"],
                "evidence_quality": pred["evidence_quality"],
            })

        all_rows = done_rows + new_rows
        out_df = pd.DataFrame(all_rows).sort_values("id").reset_index(drop=True)
        out_df.to_csv(args.output, index=False, encoding="utf-8",
                      lineterminator="\n")
        print(f"結果已儲存至 {args.output}（共 {len(out_df)} 筆）")

        if os.path.exists(args.output + ".partial"):
            os.remove(args.output + ".partial")

        print("\n=== 預測分佈 ===")
        for col in ["promise_status", "verification_timeline",
                     "evidence_status", "evidence_quality"]:
            print(f"\n{col}:")
            print(out_df[col].value_counts().to_string())

    finally:
        if tunnel:
            tunnel.stop()
            print("SSH tunnel 已關閉")


if __name__ == "__main__":
    main()
