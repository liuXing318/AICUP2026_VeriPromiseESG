# VeriPromiseESG — 用 LLM 驗證企業 ESG 永續承諾

> AI CUP 2026 VeriPromiseESG 競賽 · 繁體中文 ESG 永續報告書的承諾與證據分類

以 LLM few-shot prompting 加上規則式後處理，判斷企業永續報告書段落中：有沒有做出 ESG 承諾、有沒有提出證據、證據清不清楚，以及承諾多久後可以被驗證。

**專案重點：**

- **用實驗決定 prompt 設計。** 試過多種寫法，保留有效的，推翻直覺上合理但實際有害的。
- **比較三個模型。** 同時考量準確率、速度、成本和部署方式，在自架開源模型和商用 API 之間做取捨。
- **完整可跑的推論流程。** 能穩定跑完 2,000 筆，支援並行、斷點續跑、失敗重試和提交格式檢查。
- **正視資料問題。** 針對極度不平衡的類別合成補充資料，並處理標籤依賴關係和 N/A 解析等陷阱。

## 任務

每筆資料是一段繁體中文永續報告書文字，要預測 4 個標籤：

| 標籤 | 類別 | 權重 |
|------|------|------|
| `promise_status` | Yes / No | 20% |
| `evidence_status` | Yes / No / N/A | 30% |
| `evidence_quality` | Clear / Not Clear / Misleading / N/A | **35%** |
| `verification_timeline` | already / within_2_years / between_2_and_5_years / more_than_5_years / N/A | 15% |

這 4 個標籤有依賴關係：

- 沒有承諾（promise = No）時，後面三個標籤都是 N/A。
- 有承諾時，evidence 只能是 Yes 或 No，timeline 必須填具體時間。
- 沒有證據（evidence = No）時，evidence_quality 是 N/A。

資料規模：訓練集 1,000 筆、驗證集 1,000 筆、測試集 2,000 筆。

## 方法

```
段落文字 ──▶ System prompt + 5 個 few-shot 範例 ──▶ LLM
                                                   │
         ┌─────────────────────────────────────────┘
         ▼
  promise_status → promise_string → evidence_status → evidence_string
  → verification_timeline → evidence_quality
         │
         ▼
  Parse + 規則式後處理（修正邏輯不一致）──▶ 提交 CSV
```

- **先判斷，再摘錄。** 模型先輸出 `promise_status`，再摘錄 `promise_string`。如果順序相反，模型會因為已經抄出一段文字而偏向判 Yes。
- **用摘錄語句當作推理過程。** 官方訓練資料本來就附有 `promise_string` 和 `evidence_string`。讓模型先把承諾和證據的句子抄出來，再判斷 `evidence_quality`，等於讓模型聚焦在關鍵語句上，同時仍能看到完整原文。
- **Few-shot 範例的組成。** 共 5 個範例（1 個 No、4 個 Yes），涵蓋 Clear / already、Not Clear / between_2_and_5、無證據、Clear / more_than_5 等情況。
- **規則式後處理。** 由程式強制套用標籤之間的依賴關係。例如模型輸出 promise = Yes 卻給了 timeline = N/A 時，改成 `between_2_and_5_years`，因為標註定義規定「沒有明確目標年份」屬於這一類。

## 開發過程中的實驗發現

以下這些做法都是實際試過之後才決定保留或推翻的：

| 嘗試 | 結果 | 最終做法 |
|------|------|-----------|
| 把標籤依賴規則寫進 prompt | 干擾模型判斷，準確率下降 | prompt 只寫標註定義，規則交給程式後處理 |
| 限制 `promise_string` / `evidence_string` 的摘錄字數 | 準確率下降 | 不限字數，讓模型完整摘錄 |
| 精簡 system prompt | 細節變少後表現變差 | 保留完整定義，包括「持續推進」「努力改善」這類字眼屬於 Not Clear 的提示 |
| GPT-OSS-20B 在長輸出時回傳空內容 | 部分資料拿不到預測 | 偵測到空回應時，拿掉 few-shot 範例重試一次 |
| 用 Python 的 sshtunnel 套件長時間推論 | 跑超過約 3 小時會斷線 | 改用系統 SSH 建 tunnel，腳本加上 `--no-tunnel` |

> 這些比較都是在小樣本上觀察到的。結果一節會說明為什麼樣本數不夠是這個專案最大的教訓。

## 模型比較與取捨

| 模型 | 部署方式 | 10 筆驗證 | Public Leaderboard | 速度 | 成本 |
|------|---------|----------|--------------------|------|------|
| GPT-OSS-20B | 實驗室 DGX Spark + LiteLLM | 78.5% | 0.5071 | 約 10 秒/筆 | 自有硬體，無 API 費用 |
| GPT-5.4-mini | OpenAI API | 75.5% | **0.5483** | 約 0.2 秒/筆 | 2,000 筆約 5–6 美元 |
| Qwen 2.5 7B | 實驗室 DGX Spark | 66.3% | — | 約 1.2 秒/筆 | 自有硬體 |

Qwen 2.5 7B 在 `verification_timeline` 只答對 36%，而且完全不會預測 Not Clear，所以沒有用它跑完整測試集。

## 工程化的推論流程

- **並行處理：** 用 `ThreadPoolExecutor` 同時發送多個 API 請求。
- **容錯：** 每 50 筆存一次檔，中斷後可以用 `--resume` 從斷點接著跑。
- **重試：** 失敗時用 exponential backoff 重試，並針對 OpenAI 的 rate limit 另外處理；重試仍失敗就填入 fallback 預測，確保每一筆都有結果。
- **提交前檢查：** [`validate_submission.py`](scripts/validate_submission.py) 檢查欄位順序、ID 範圍、值域和邏輯規則；[`fix_submission.py`](scripts/fix_submission.py) 自動修復 NaN、遺漏的 ID 和邏輯不一致。
- **N/A 陷阱：** pandas 預設會把字串 `"N/A"` 讀成 NaN，導致提交檔出現空值。提交檔的檢查和修復工具在讀檔時會關掉這個行為，評分腳本也會把 NaN 統一轉回 N/A 再比對。

## 資料問題：極度不平衡的類別

訓練集中，`Misleading` 只有 1 筆，`within_2_years` 只有 13 筆，few-shot 的模型幾乎不會預測這兩類。為此合成了 40 筆擴增資料（[`datasets/augmented_rare_samples.csv`](datasets/augmented_rare_samples.csv)）：25 筆 Misleading、15 筆 within_2_years，欄位格式與官方資料一致，準備給後續的微調使用。

## 結果與反思

兩條推論管線都跑完了 2,000 筆測試集，Public Leaderboard 各標籤的分數如下：

| 模型 | promise | evidence | quality | timeline | **Weighted** |
|------|---------|----------|---------|----------|--------------|
| GPT-OSS-20B | 0.7323 | 0.5600 | 0.3308 | 0.5121 | 0.5071 |
| GPT-5.4-mini | 0.7390 | 0.6408 | 0.3591 | 0.5501 | **0.5483** |

- **本地驗證的樣本數太少。** 開發時只用 10 筆驗證資料比較，GPT-OSS-20B 看起來比較好。到了 Public Leaderboard，兩個模型的分數都大幅下滑，排名也反過來。10 筆樣本的差距不足以支撐判斷，上面的實驗發現也有同樣的限制。下一步應該先用完整的 1,000 筆驗證集建立可信的評估。
- **`evidence_quality` 是最大瓶頸。** 它的權重最高（35%），分數卻最低，主要原因是模型幾乎不會預測 Not Clear 和 Misleading。這也是合成稀少類別資料、規劃後續微調的原因。
- **在這個任務上，商用小模型比較划算。** GPT-5.4-mini 快了約 50 倍，Public 分數也比較高，成本只有幾美元。自架模型的優勢在資料不必送出、沒有 API 費用，但需要自己處理連線穩定性和推論速度。

## 專案結構

```
├── scripts/
│   ├── inference.py             # GPT-OSS-20B 推論（DGX Spark + SSH tunnel）
│   ├── inference_openai.py      # GPT-5.4-mini 推論（OpenAI API）
│   ├── evaluate.py              # 驗證集加權準確率 + confusion matrix
│   ├── validate_submission.py   # 提交格式檢查
│   └── fix_submission.py        # 修復 NaN / 遺漏 ID / 邏輯不一致
├── datasets/
│   ├── README.md                # 官方資料取得說明
│   └── augmented_rare_samples.csv
├── submissions/                 # 兩份測試集預測結果
└── docs/
    ├── AICUP_strategy.md        # 原始策略規劃與完整 system prompt
    └── PROJECT_OVERVIEW.md      # 專案進度總覽
```

## 使用方式

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 OPENAI_API_KEY 或 DGX 連線資訊
```

官方資料集不包含在本 repo 中，請參考 [`datasets/README.md`](datasets/README.md) 自行取得。

```bash
# OpenAI API 版本
python scripts/inference_openai.py --input datasets/vpesg4k_test_2000.csv --output submissions/submission_openai.csv

# DGX 版本（若已自行建立 SSH tunnel，請加上 --no-tunnel）
python scripts/inference.py --input datasets/vpesg4k_test_2000.csv --output submissions/submission_oss.csv

# 驗證集評分
python scripts/evaluate.py --pred <預測CSV> --gold datasets/vpesg4k_val_1000.csv

# 檢查提交格式
python scripts/validate_submission.py submissions/submission_openai.csv
```

用 `--sample N` 可以只跑前 N 筆，用 `--resume` 可以從中斷的地方繼續。

> ⚠️ 用 pandas 讀這份資料時，請加上 `keep_default_na=False, na_values=[]`，否則字串 `"N/A"` 會被轉成 NaN。

## 未來方向

- 用 QLoRA 微調 GPT-OSS-20B，訓練資料為訓練集 1,000 筆 + 驗證集 500 筆 + 擴增資料 40 筆。
- 在完整驗證集上評估，並針對稀少類別調整 prompt 或做 class rebalancing。
