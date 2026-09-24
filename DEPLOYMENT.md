# 跨服务器部署与迁移

本文按当前代码与配置整理，适用于把已有 `fulltext_workflow` 实例迁到另一台服务器。先在源服务器完成一致性备份，再在目标服务器安装依赖、恢复数据并验证。历史设计稿与阶段性报告保留当时状态，日常命令以本指南及 `fulltext_workflow/` 下的操作文档为准。

## 1. 部署边界

- Python 建议 3.10–3.12；从仓库根目录安装 `requirements.txt`。`mineru[core]` 及其模型资源可能较大，目标机应预留磁盘空间；PDF 解析速度取决于 CPU/GPU 环境。
- `fulltext_workflow/config.py` 以自身目录为基准固定使用 `data/kg_fulltext.db`、`raw/` 和 `output/`；仓库路径可以改变，运行数据目录目前不能单靠环境变量重定向。
- `.env` 位于仓库根目录；也支持 `fulltext_workflow/.env`，后者的非空值优先。迁移时核对两处配置，避免旧配置覆盖新服务器设置。密钥应通过安全渠道单独传输，不随代码提交。
- `run_pipeline.ps1`、`run_gap_ui.ps1` 是 Windows/PowerShell 入口。Linux 上直接使用虚拟环境的 Python/Streamlit 命令。
- 这是单机本地 SQLite 工作流。不要让两台服务器同时写同一份数据库，也不要把 SQLite 主库放在供多机并发写入的共享目录；切换前应停止源机写入任务。

## 2. 源服务器：冻结并备份

1. 停止 `fetch`、`extract`、周更任务和 Gap UI 运维任务；确认没有后台进程继续写数据库。若要迁移 UI 当前任务状态，先等待其完成。
2. 记录当前代码提交或工作树版本。未提交的代码/文档改动应随部署包一起交付，否则目标服务器可能运行不同版本。不要复制旧 `.venv`，应在目标机重建。
3. 对 SQLite 做一致性备份。以下命令在仓库根目录执行，不会修改源库：

   ```powershell
   python -c "import sqlite3; s=sqlite3.connect('fulltext_workflow/data/kg_fulltext.db'); d=sqlite3.connect('kg_fulltext.backup.db'); s.backup(d); d.close(); s.close()"
   ```

   Linux 把命令中的 `python` 换成 `python3`。不要在源库仍有写入时用普通文件复制代替 SQLite backup。

4. 把备份库、根目录 `.env`（以及存在时的 `fulltext_workflow/.env`）、`fulltext_workflow/raw/` 通过受保护的传输渠道交付目标机。若用过 IF 导入，连同 `fulltext_workflow/data/jcr.csv` 交付；若需要保留已生成的图谱、报告、运维任务日志及其他本地文件，连同 `fulltext_workflow/output/` 交付。`data/` 下其他人工清单或本地输入文件按需一并迁移。这些运行文件均被 `.gitignore` 排除，单纯 `git clone` 不会带上。

## 3. 目标服务器：安装与恢复

在目标机获取与源机一致的代码版本后，在仓库根目录创建环境。示例：

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
# Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

将备份库恢复为 `fulltext_workflow/data/kg_fulltext.db`，并将上一步选定的 `.env`、`raw/`、`jcr.csv`、`output/` 和本地输入文件放回原相对位置。先在目标机检查 `.env` 的 API 地址、密钥、模型、校园网/VPN 条件及 `PATHOLOGY_API_BASE_URL`。`FULLTEXT_PUBLISHER_DIRECT` 在代码中默认开启，但 IEEE 直连依赖目标机的校园网/VPN 出口；无此条件可在 `.env` 显式设置 `FULLTEXT_PUBLISHER_DIRECT=false`。

如果只需要保留论文和抽取结果，数据库是核心；不迁移 `raw/` 会失去已下载的 JATS、PDF 和 MinerU 缓存，后续全文处理可能重新下载或解析。`output/` 保存生成的报告、图文件及 UI 周更日志；不迁移可按需重新生成。

## 4. 验收与启动

先检查备份库完整性与论文数；这一步以 SQLite 只读模式打开数据库，不运行项目迁移代码：

```powershell
# Windows PowerShell，仓库根目录
cd fulltext_workflow
..\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('file:data/kg_fulltext.db?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print('papers:', c.execute('SELECT COUNT(*) FROM papers').fetchone()[0]); c.close()"
```

```bash
# Linux，仓库根目录
cd fulltext_workflow
../.venv/bin/python -c "import sqlite3; c=sqlite3.connect('file:data/kg_fulltext.db?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print('papers:', c.execute('SELECT COUNT(*) FROM papers').fetchone()[0]); c.close()"
```

完整性结果应为 `ok`，论文数应与源机备份时一致。随后执行应用层验收：

```powershell
# Windows PowerShell，fulltext_workflow/ 下
..\.venv\Scripts\python.exe main.py stats
..\.venv\Scripts\python.exe main.py embedding-preflight
```

```bash
# Linux，fulltext_workflow/ 下
../.venv/bin/python main.py stats
../.venv/bin/python main.py embedding-preflight
```

`stats` 和 `embedding-preflight` 都会先调用 `init_db()`，可能迁移 schema，因此应在保留备份、通过只读检查后运行。`stats` 应显示迁移后的论文、抽取与图谱统计；`embedding-preflight` 默认不发起网络请求，未使用 embedding 可跳过。然后验证目标服务器可访问所需外部服务，再按需执行 `fetch --since-days 14` 或周更。

启动 Gap UI：

```powershell
# Windows PowerShell，fulltext_workflow/ 下
.\run_gap_ui.ps1
```

```bash
# Linux，fulltext_workflow/ 下；默认仅监听本机
../.venv/bin/python -m streamlit run gap_ui.py --server.address 127.0.0.1 --server.port 8501
```

Streamlit UI 含写入和运维操作。远程访问时建议通过 SSH 隧道或已有的受控反向代理访问本机 `8501`，不要直接向公网开放。迁移后在 UI 中检查文献统计、周热点、证据页和运维状态；旧 `output/ops_jobs/current.json` 若指向源机未完成任务，不应直接在目标机续跑，应先核查并处理该历史状态。

Windows 周更用 `run_pipeline.ps1 -Stage weekly`。Linux 可按相同顺序执行：`fetch --since-days 14`、`enrich-s2`、`fetch-fulltext`、`extract --limit 0 --core-only`、`compute-gap-lifecycle`、`hotspot-report`、`hotspot-brief`、`stats`。这条周更链不执行 `build` / `analyze`；需要更新导出图谱和静态 Gap 报告时再执行这两个命令。UI「运维」页的周更默认跳过旧全文的 PDF 重试和摘要升级重抽，行为见 [流水线指南](fulltext_workflow/PIPELINE.md)。

## 5. 回退

保留源机原始库和迁移时的备份库，直到目标机完成只读验收及首轮预期任务。回退时先停止目标机的写入任务，再将流量切回源机。若目标机已经产生新写入，两个 SQLite 文件不会自动合并，应决定以哪一份为准并单独备份。

## 6. Docker Compose 部署

仓库根目录提供 [Dockerfile](Dockerfile)、[compose.yaml](compose.yaml) 和 [.dockerignore](.dockerignore)。这是一套单服务器 CPU 基线：一个容器运行 Streamlit UI，UI「运维」页可以在同一容器中启动周更子进程；CLI 任务用同一镜像临时启动。目标机需预先安装 Docker Engine 与 Compose 插件，以下在 **Linux 服务器的仓库根目录**执行。

### 6.1 准备配置和持久目录

```bash
cp .env.example .env
# 编辑 .env，填入真实的 PUBMED_EMAIL、LLM API key、模型和所需 API 地址
mkdir -p docker-data/data docker-data/raw docker-data/output docker-data/cache
```

`.env` 由 Compose 的 `env_file` 注入容器，不会进入镜像；`.dockerignore` 也排除密钥和本地数据。`docker-data/` 已加入 `.gitignore`，四个目录分别映射到容器的 `data/`、`raw/`、`output/` 和模型缓存。代码与数据分离，重建镜像不会清掉它们。代码中部分变量会读取仓库内 `.env` 并覆盖进程环境，因此镜像中不应包含其他旧 `.env` 文件；本配置已经将其从构建上下文排除。

若从旧服务器迁移，把第 2 节生成的 `kg_fulltext.backup.db` 放到 `docker-data/data/kg_fulltext.db`；再把源机 `fulltext_workflow/raw/`、`data/jcr.csv`、所需的其他本地数据和 `output/` 内容分别放进对应 `docker-data/` 目录。迁移时先停止源机写入任务，并保留原始备份。没有旧库时保持 `docker-data/data/` 为空。

### 6.2 构建和验收

```bash
docker compose build
```

已有数据库时，先以只读模式检查完整性：

```bash
docker compose run --rm --no-deps gap-ui python -c "import sqlite3; c=sqlite3.connect('file:data/kg_fulltext.db?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print('papers:', c.execute('SELECT COUNT(*) FROM papers').fetchone()[0]); c.close()"
docker compose run --rm --no-deps gap-ui python main.py stats
```

第一条应输出 `ok`，且论文数应与源机一致。第二条会执行 schema 初始化/迁移，因此必须先保留源库备份。新库则先执行：

```bash
docker compose run --rm --no-deps gap-ui python main.py init
```

需要首次抓取和抽取时，再运行 `docker compose run --rm --no-deps gap-ui python main.py run-db --limit 30 --core-only` 试跑。它会访问外部文献源和 LLM，并可能进行耗时的 PDF/MinerU 处理；确认环境与配额后再扩大规模。Compose 启动 UI 本身不会自动建库。

### 6.3 启动 UI 与日常命令

```bash
docker compose up -d
docker compose ps
docker compose logs -f gap-ui
```

容器内 Streamlit 监听 `0.0.0.0:8501`，Compose 只把主机 `127.0.0.1:8501` 映射出去。在个人电脑建立 `ssh -L 8501:127.0.0.1:8501 <user>@<server>` 隧道后访问 `http://localhost:8501`；已有反向代理时也可让代理连接服务器本机该端口。UI 有运维写入能力，应使用受控访问入口。

常用 CLI 示例：

```bash
docker compose run --rm --no-deps gap-ui python main.py stats
docker compose run --rm --no-deps gap-ui python main.py fetch --since-days 14
docker compose run --rm --no-deps gap-ui python main.py build
docker compose run --rm --no-deps gap-ui python main.py analyze
```

UI「运维」页可执行同一库上的周更；如果用 CLI 跑长任务，避免同时从 UI 启动写库任务。Linux 容器不运行仓库的 `.ps1` 脚本；完整周更顺序见第 4 节。退出 UI 用 `docker compose down`；不要删除 `docker-data/`。升级代码后执行 `docker compose build` 和 `docker compose up -d`，并在运行 schema 迁移前备份数据库。

本仓库的 MinerU 可能在首次 PDF 解析时下载模型，镜像构建和首次解析需要较大空间与时间。当前 Compose 配置是 CPU 版；如需 CUDA，目标机需配置 NVIDIA 容器运行时，并为服务增加 GPU 设备预留，再将 `.env` 的 `MINERU_DEVICE` 设为 `cuda`。镜像内的 PyTorch/CUDA 依赖也须与目标 GPU 环境匹配，需在目标机单独验证。
