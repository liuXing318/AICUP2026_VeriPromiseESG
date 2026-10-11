# AI CUP 2026 ESG 永續承諾驗證競賽 — 我的策略規劃

## 任務簡述

這是教育部 AI CUP 的 NLP 競賽。資料是 4000 筆繁體中文 ESG 永續報告書段落，每筆要預測四個分類標籤：

- `promise_status`（Yes/No）— 文本是否包含 ESG 承諾，權重 20%
- `evidence_status`（Yes/No/N/A）— 是否有支持證據，權重 30%
- `evidence_quality`（Clear/Not Clear/Misleading/N/A）— 證據清晰度，權重 35%（最重要）
- `verification_timeline`（already/within_2_years/between_2_and_5_years/more_than_5_years/N/A）— 預期驗證時間，權重 15%

四個標籤有邏輯依賴鏈：promise=No 時後面三個都是 N/A；evidence=No 時 quality 也是 N/A。

資料分為 train 1000 筆、val 1000 筆、test 2000 筆（無標籤）。50 家公司在三組完全重疊。最終繳交一個 CSV，欄位順序為 id, promise_status, verification_timeline, evidence_status, evidence_quality。

資料都在 datasets/ 裡。

## 我的策略

### 模型與硬體

用 OpenAI 的 GPT-OSS-20B（開放權重 MoE 模型，21B 參數 / 3.6B 活躍參數），以 Unsloth + QLoRA 做微調。(注意，其實我沒有用過LoRA調參的經驗，所以請先確認一下這個方法適不適合，若不適合請自己調整策略)

模型部署在實驗室的 DGX Spark 上，透過 SSH tunnel + LiteLLM 存取（連線方式見下方「DGX 連線資訊」）。微調訓練也在 DGX 上執行。

### 資料分割與擴增

因為訓練集稍嫌不足，因此我想從 val 1000 筆中取 500 筆併入訓練集，剩餘 500 筆驗證。用 stratified sampling 確保標籤分佈一致。

另外，由於 Misleading 僅 2 筆、within_2_years 僅 34 筆，我們額外生成了 40 筆擴增資料（25 筆 Misleading + 15 筆 within_2_years），放在專案資料夾中的 `augmented_rare_samples.csv`，欄位格式與原始訓練資料一致，id 從 90001 開始。訓練時直接 concat 進去即可。

最終訓練資料：1500（原始）+ 40（擴增）= 1540 筆。驗證資料：500 筆。

### 核心設計：先判斷再抽取的輸出格式

不是直接做四個分類，而是讓模型依序輸出完整的結構化分析。

關鍵設計是「先判斷狀態，再摘錄語句」：模型先輸出 promise_status 再輸出 promise_string，避免模型因為先硬抽了一段語句就偏向判 Yes。evidence_status 和 evidence_string 同理。

訓練資料裡本來就有 promise_string 和 evidence_string 這些中間欄位可用，雖然最終提交不需要這些欄位，但讓模型學習抽取它們有兩個作用：第一，提升分類品質；第二，讓模型在判斷後續標籤時（特別是 evidence_quality），可以參考自己已經抽取出的承諾與證據語句，而不只是看原始的長段文本。

因為模型是逐 token 生成的，生成 evidence_quality 時，前面已輸出的 promise_string 和 evidence_string 都在它的 context 中，等於幫模型做了一次注意力聚焦。但模型同時也能看到 user message 中的原始文本，所以是「聚焦 + 完整上下文」的結合。

模型的輸出格式（每行一個欄位，方便 parse）：

```
promise_status: Yes
promise_string: （摘錄的承諾語句）
evidence_status: Yes
evidence_string: （摘錄的證據語句）
verification_timeline: already
evidence_quality: Clear
```

### 我們設計好的 System Prompt

以下是微調與推論時使用的 system prompt，直接用這個：

```
你是一位 ESG 永續報告分析專家，負責從企業永續報告書段落中標註承諾與證據資訊。

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
- between_2_and_5_years：2-5 年內可驗證，或承諾未明示具體目標完成年份時選用 (注意!承諾未明示句體悟標完成年分時也是屬於此項!)
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
promise_string: <承諾語句或N/A>
evidence_status: <Yes/No/N/A>
evidence_string: <證據語句或N/A>
verification_timeline: <already/within_2_years/between_2_and_5_years/more_than_5_years/N/A>
evidence_quality: <Clear/Not Clear/Misleading/N/A>
```

### 後處理

模型輸出後，程式 parse 六個欄位，取出需要的四個提交欄位，並用硬規則修正邏輯不一致的預測（比如模型輸出了 promise=No 但 timeline 不是 N/A 的情況）。

### 提交格式注意事項

訓練資料中空值是 NaN（pandas null），但提交的 CSV 必須使用字串 "N/A"，不能是空值。生成 CSV 時要確保所有 NaN 都轉為字串 "N/A"，且編碼為 UTF-8 無 BOM、Unix 換行符。

### 其他注意點

- 多段抽取用全形「 ｜ 」連接（約 30% 的 promise_string 和 evidence_string 是這樣）
- GPT-OSS-20B 使用 Harmony response format，微調時要注意 chat template

---

## DGX 連線資訊

模型部署在實驗室的 DGX Spark 上，透過 LiteLLM 提供 OpenAI-compatible API（遠端 port 4000），本機以 SSH tunnel 轉發後存取。

連線資訊（host / 帳號 / 密碼）不放在 repo 中，請複製 `.env.example` 為 `.env` 後填入。也可以先用系統 SSH 建立 tunnel，再讓腳本加上 `--no-tunnel`：

```bash
ssh -L 8080:127.0.0.1:4000 <user>@<dgx-host>
```

建立 tunnel 後，可透過 OpenAI-compatible API 呼叫模型：

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8080", api_key="dummy")
resp = client.chat.completions.create(
    model="gpt-oss-20b",
    messages=[{"role": "user", "content": "Hello"}]
)
```

微調訓練也在此 DGX 上執行（128GB 統一記憶體，足以跑 QLoRA）。
