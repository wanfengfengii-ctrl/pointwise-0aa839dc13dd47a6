# 江北桥梁监测固定版采集站

江北区桥梁监测中心用固定门户发布版交接北河桥监测结果。白班保全原页，质检员签发超限明细，夜班只开站库即可按班报号复核原读和出处。运行环境为 Python 3.11 标准库和随 Python 提供的 SQLite。

## 运行

```sh
python3 -B check_project.py
python3 -B -m handover.cli demo
```

`check_project.py` 由运行平台提供，执行包 `tests` 下的完整原回归。单独导出源码时也可直接执行 `python3 -B -m unittest discover -s tests -t . -v`。`demo` 用临时目录里的两份真实数据库发布固定版、登记任务、逐页留证、实收、签报，再关闭门户并重新打开站库按号领取。成功输出真实领取结果及场景记录，业务错误返回非零退出码。

## 白班到夜班

1. 门户编辑把测点台账和仪器读数发成固定版。每行含字符串 `point_id`、整数 `number`、整数 `raw` 和字符串 `source_version`。同版内 ID 和编号各自唯一，输入按编号规范化。
2. 质检员登记具名修订。采集员把任务号绑定到栏目、版号、修订和当时的页长。再次登记同参可找回原进度。
3. 采集员按原版从编号游标继续读页。原页和续点共同持久化，成功保存结束页后可交件。源读取失败时，按原续点重试，即使门户另发新版也能续采。合法空版包含一张空结束页。
4. 实收独立检查状态、完整页链及对应留存原件。坏件拒收。原读乘固定有理比例，再加整数零点，得到精确微米值。严格大于有理阈值才算超限。
5. 实收事务共同发布批次、计算、原页和出处。同任务同件返回原成果，改件冲突。提交失败回滚正式成果，原采集件可重投。
6. 质检员按批次签班报。超限明细按原编号排序，比例为超限数除以总行数。全合格非空批比例为零，空批比例为空。同批次重签仍领原号。
7. 夜班只打开站库，按班报号领取计算和原页。页序从 1 起，页内位置从 0 起。即使没有行，仍可领该批的结束页。

样例 A、B、C 的编号是 10、20、30，原读是 2、3、0。比例 3/2、零点 1、阈值 4 时结果依次为 4、11/2、1 微米，班报仅列 B，超限比为 1/3。样例见 `samples/north_river.json`。

## Python 接口

`handover.station.open_portal(path)` 返回固定版门户。`portal.catalog.publish(column, release_id, rows)` 接收 `portal.rows.SourceRow` 对象序列。`portal.page(column, release_id, cursor, page_length)` 以 `None` 起读，使用原样返回的 `next_cursor` 续读。游标绑定栏目、版号及锚点。`portal.close()` 关闭门户。

`handover.station.open_station(path)` 打开站库，重复初始化保留已登记的业务数据。用 `station.profiles.set_profile(revision, scale, zero, limit)` 登记口径，`scale` 与 `limit` 接收整数或 `fractions.Fraction`。调用 `station.capture_from(portal, page_length=2)` 获得采集服务。`capture.start_fixed(task_id, column, release_id, revision)` 登记，`capture.pull(task_id)` 推进一步，`capture.evidence_for(task_id)` 返回按序原页。`station.jobs.get(task_id)` 可离线查询进度。

`station.admission.admit(task_id, pages)` 返回正式批次和原件。`station.signer.sign(batch_id)` 返回固定班报，`station.reader.lookup(report_id)` 返回班报、批次、各行出处及原页。领取服务只依赖站库。未知号用相应的 `LookupError` 子类报告，冲突及无效业务输入用相应的 `ValueError` 子类报告，数据库错误由 `sqlite3` 报告。用 `station.close()` 关闭站库。

## 多检区交班（同一固定发布版）

白班可在同一固定发布版上按甲、乙、丙等检区交班，检区是包含端点的授权编号范围。多检区是固定版采集的可选扩展：不传 `zones` 的旧调用、旧证据件和旧班报结构全部保持有效。

1. `capture.start_fixed(task_id, column, release_id, revision, zones={区名: (首, 末)})` 登记多检区任务，`zones` 为可选关键字参数。检区可重叠；同任务再次登记同参找回原进度，范围不一致报 `TaskConflict`。
2. 受限采集仍以发布版真实页游标续读，门户只交付授权范围**并集**内的原读：范围外编号在门户侧即被剔除，不得到站；重叠测点在原页序列中只保留一份，页内可空，发布版真实结束页（可能为空）作为结束证据持久化，读源失败后按原续点续采。
3. 多检区任务的 `capture.evidence_for(task_id)` 与 `station.evidence_for(task_id)` 返回
   `{'pages': 原页序列, 'coverage': {区名: {'release_id': 版号, 'range': [首, 末], 'proof': 证据}}}`。
   `proof` 是绑定发布版、检区范围与受限采集结束页的 SHA-256 证据令牌。单区任务仍返回原页序列。
4. `station.admission.admit(task_id, package)` 对多检区接收同形字典数据。实收逐区核定完整性：错版报 `WrongFixedRelease`，越权或重复共享测点报 `ZoneViolation`，缺结束证据、缺区键或证据令牌不符报 `MissingZoneProof`，篡改留存原件报 `OriginalPageMismatch`。可删除或替换单区键后用同形数据复投；任何一区未取证都会阻止整单。整个实收在一个事务内提交，失败回滚不留半件，原采集件可重投，同任务同件返回原成果。
5. 真正没有原读、且由真实空结束页证实为空的检区才签发；班报按检区给出 `total_count`、编号有序的超限明细 `details`（沿用旧明细结构）和精确比例 `over_limit_ratio`（`fractions.Fraction`，空区为 `None`）。共享测点分别计入所属检区，并引用同一原页同一位置。多检区班报顶层 `details` 为空、`over_limit_ratio` 为 `None`，逐区结果在 `report.zones[区名]`。
6. `station.reader.lookup(report_id)` 对多检区班报额外返回同形 `coverage`，并在 `report.zones` 给出逐区 `{total_count, details, over_limit_ratio}`；旧班报的这两项为 `None`。领取仍只依赖站库，可离线复核报告、原读、出处与覆盖证据。

## 操作命令

运行 `python3 -B -m handover.cli --help` 查看子命令。全局选项 `--portal` 和 `--station` 放在子命令之前，默认文件分别为 `portal.sqlite` 和 `station.sqlite`。`init` 幂等建库。`publish COLUMN RELEASE FILE` 从 JSON 行数组发布固定版，`page COLUMN RELEASE LENGTH` 读页并可用 `--cursor` 续读。`profile REVISION SCALE ZERO LIMIT` 登记口径，CLI 用分数字符串传入精确比例与阈值。`start TASK COLUMN RELEASE REVISION --page-length 2` 登记，多检区任务追加 `--zones 甲:10-20,乙:25-30` 形式的逗号分隔检区（`区名:首-末`，端点包含）。`pull TASK` 推进一步，`evidence TASK` 输出可保存的原页件 JSON（单区为数组，多检区为含 `pages` 与 `coverage` 的对象），`admit TASK FILE` 自动识别两种件形并提交。`sign BATCH` 签报，`lookup REPORT` 可离线领取。JSON 输出中的精确分数用字符串表示，空比例用 `null` 表示。
