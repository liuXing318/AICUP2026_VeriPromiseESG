# datasets

官方資料集依競賽規範不在此 repo 中公開，請自行從 AI CUP 2026 VeriPromiseESG 競賽頁面取得，並放在此資料夾：

| 檔案 | 筆數 | 說明 |
|------|------|------|
| `vpesg4k_train_1000.csv` | 1000 | 訓練集（含標籤與 promise_string / evidence_string） |
| `vpesg4k_val_1000.csv` | 1000 | 驗證集（含標籤） |
| `vpesg4k_test_2000.csv` | 2000 | 測試集（無標籤，ID 12001–14000） |
| `sample_submission_format.csv` | — | 官方提交格式範本 |

本 repo 僅附上自製的 `augmented_rare_samples.csv`：40 筆合成的稀少類別資料（25 筆 Misleading + 15 筆 within_2_years），欄位格式與官方訓練資料一致，ID 從 90001 開始。
