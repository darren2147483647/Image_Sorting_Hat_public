# 圖像分類帽 (Image Sorting Hat)

## 目標

- 建立一個影像管理系統
- 自動掃描影像庫，紀錄角色或作品的tag資訊
- 以資料庫維護tag層級關係
- 提供web介面進行管理和搜尋

## 設計

此工具的三個組件相互獨立，可以分別替換或保存
1. 程式 (frontend, backend): 可視化使用者介面，負責搜尋與管理
2. 影像資料庫 (images): 影像儲存位置
3. 紀錄資料庫 (data): 記錄tag資訊, db, json

## 使用

### Windows

- 初次建立
```cmd
# vite
cd frontend
npm install

# venv
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

- 前端
```cmd
cd frontend
npm run dev
```

- 後端
```cmd
cd backend
.venv\Scripts\activate
python main.py
```

### Linux / macOS

- 初次建立
```bash
# vite
cd frontend
npm install

# venv
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- 前端
```bash
cd frontend
npm run dev
```

- 後端
```bash
cd backend
source .venv/bin/activate
python main.py
```

## 疑難排解

- **Windows 上 `pip install` 找不到套件、或執行 `pytest`／`python main.py` 出現 `ModuleNotFoundError`，但明明已經 `pip install` 過**：通常是因為系統 PATH 上有其他 Linux 相容的 Python（例如 Git Bash、MSYS2/mingw64、WSL 附帶的 python.exe）排在專案的 `.venv` 前面，`python`／`pip` 實際上呼叫到了那一個，不是這個專案的 venv。用 `where python`（cmd/PowerShell）確認目前 `python` 實際指向哪裡；確定問題後，直接用完整路徑呼叫這個專案的直譯器最保險：`backend\.venv\Scripts\python.exe -m pytest`、`backend\.venv\Scripts\python.exe main.py`，不依賴目前 shell 的 `python` 指到哪裡。
- **在 Linux 上，某些資料夾名稱被拒絕，但這個名稱在 Linux 檔案系統上其實合法**：角色／作者名稱的驗證規則是照 Windows 資料夾命名規則設計的（禁止 `<>:"/\|?*`、結尾點/空白、`CON`/`PRN` 等保留字），比 Linux 實際允許的範圍更嚴格。這是刻意的限制，不是 bug：這樣命名出來的資料夾，日後不管搬到 Windows 還是 Linux 都能用，反過來則不一定。
- **後端啟動時印出「⚠️ 設定的紀錄目錄不存在」**：代表「紀錄目錄」設定指向的路徑目前連不到——最常見是外接硬碟還沒接上，或路徑打錯字。後端這次會先用預設的 `data/` 頂著繼續啟動，不會拒絕啟動；確認硬碟已接上／路徑正確後，到掃描頁面重新確認「紀錄目錄」設定，再重新啟動後端即可。