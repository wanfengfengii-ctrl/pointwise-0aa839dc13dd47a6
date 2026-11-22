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

## 操作命令

运行 `python3 -B -m handover.cli --help` 查看子命令。全局选项 `--portal` 和 `--station` 放在子命令之前，默认文件分别为 `portal.sqlite` 和 `station.sqlite`。`init` 幂等建库。`publish COLUMN RELEASE FILE` 从 JSON 行数组发布固定版，`page COLUMN RELEASE LENGTH` 读页并可用 `--cursor` 续读。`profile REVISION SCALE ZERO LIMIT` 登记口径，CLI 用分数字符串传入精确比例与阈值。`start TASK COLUMN RELEASE REVISION --page-length 2` 登记，`pull TASK` 推进一步，`evidence TASK` 输出可保存的原页件 JSON，`admit TASK FILE` 提交该 JSON。`sign BATCH` 签报，`lookup REPORT` 可离线领取。JSON 输出中的精确分数用字符串表示，空比例用 `null` 表示。
