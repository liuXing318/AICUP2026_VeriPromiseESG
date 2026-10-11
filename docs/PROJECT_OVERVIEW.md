# VeriPromiseESG — 專案說明

## 目前進度

已完成 zero/few-shot 推論基線，兩條管線皆可跑完整 2000 筆測試集並產出提交檔：

| 管線 | 模型 | 加權準確率（10 筆驗證集） | 速度 | 備註 |
|------|------|--------------------------|------|------|
| `inference.py` → DGX | GPT-OSS-20B | **78.5%** | ~10s/筆 | SSH tunnel 不穩定 |
| `inference_openai.py` → OpenAI | GPT-5.4-mini | 75.5% | ~0.2s/筆 | 快 50 倍，費用約 $5-6/2000 筆 |
| （已測試）Qwen 2.5 7B | — | 66.3% | ~1.2s/筆 | timeline 極差(36%)，不預測 Not Clear |

下一步是 QLoRA 微調 GPT-OSS-20B 來提升準確率（尚未開始）。

## 各檔案說明

### 核心推論管線

- **`scripts/inference.py`** — DGX 推論管線。透過 SSH tunnel 連到 DGX Spark 上的 LiteLLM，用 GPT-OSS-20B 做 few-shot 分類。支援並行 workers、斷點續跑（`--resume`）、定期存檔。
- **`scripts/inference_openai.py`** — OpenAI API 版本。邏輯相同，但走 OpenAI 官方 API（GPT-5.4-mini），多了 rate limit 退避機制。

### 評估與驗證工具

- **`scripts/evaluate.py`** — 計算加權準確率 + confusion matrix。用法：`python scripts/evaluate.py --pred <預測CSV> --gold <答案CSV>`
- **`scripts/validate_submission.py`** — 檢查提交 CSV 格式是否符合競賽要求（欄位順序、2000 筆、ID 12001-14000、值域合法、邏輯規則）。
- **`scripts/fix_submission.py`** — 自動修復 CSV 的 NaN / 遺漏 ID / 邏輯不一致問題，直接覆寫原檔。

### 資料集（`datasets/`）

| 檔案 | 筆數 | 用途 |
|------|------|------|
| `vpesg4k_train_1000.csv` | 1000 | 訓練集（有標籤 + promise_string / evidence_string） |
| `vpesg4k_val_1000.csv` | 1000 | 驗證集（有標籤） |
| `vpesg4k_test_2000.csv` | 2000 | 測試集（無標籤，最終預測目標） |
| `augmented_rare_samples.csv` | 40 | 合成稀少類別資料（25 Misleading + 15 within_2_years），ID 90001+ |
| `sample_submission_format.csv` | — | 官方提交格式範本 |
| `AI_CUP_2026_VeriPromiseESG_Submission_Guidelines.pdf` | — | 官方提交規範文件 |

**標籤分佈（訓練集）：**
- promise: Yes 814 / No 186
- evidence_quality: Clear 552 / Not Clear 124 / **Misleading 1**
- verification_timeline: already 366 / between_2_and_5 238 / more_than_5 197 / **within_2_years 13**

### 提交結果（`submissions/`）

- **`submission_oss.csv`** — GPT-OSS-20B 跑完的 2000 筆完整提交（Public 0.5071）
- **`submission_openai.csv`** — GPT-5.4-mini 跑完的 2000 筆完整提交（Public 0.5483）

### 文件（`docs/`）

- **`AICUP_strategy.md`** — 完整競賽策略文件，包含任務定義、prompt 設計思路、輸出格式設計、DGX 連線資訊。
- **`PROJECT_OVERVIEW.md`** — 本文件。

## 關鍵技術設計

1. **Prompt 設計**：完整的 system prompt + 5 個 few-shot 範例（覆蓋 No、Clear/already、Not Clear/between_2_and_5、No evidence、Clear/more_than_5）。不要精簡 prompt，每個細節都有意義。
2. **Chain-of-thought**：模型先判斷 status 再摘錄 string。string 摘錄是中間推理步驟，讓模型在判斷 evidence_quality 時可以參考已抽取出的承諾與證據語句，而不只是看原始的長段文本。
3. **Post-process**：不在 prompt 裡寫邏輯規則（寫了反而干擾模型），邏輯修正全靠程式端硬規則：
   - promise=No → 後三個全 N/A
   - promise=Yes → evidence 不能 N/A（fallback 改 No）、timeline 不能 N/A（fallback 改 between_2_and_5_years）
   - evidence=No 或 N/A → quality=N/A
4. **最大痛點**：
   - `verification_timeline` 是目前最弱的標籤
   - `Misleading` 在訓練集只有 1 筆、`within_2_years` 只有 13 筆，模型幾乎不會預測到
