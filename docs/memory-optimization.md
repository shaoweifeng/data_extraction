# 内存优化待办

> 记录时间：2026-09-04  
> 背景：服务器部署时，上传较大的初筛索引文件（RIS/XML）会导致进程 OOM 崩溃

---

## 根因诊断

### 🔴 P0：解析阶段全量加载 + 多次内存放大

**位置**：`core/executors/parsers/parser.py` → `parse_directory()` / `convert_to_xml()`  
**位置**：`core/executors/handlers/parse_handler.py` → `execute()` / `_generate_split_xmls()`

**问题**：解析流程存在 3~4 倍内存放大：

```
parse_directory()   → 全量 list[dict]       ← 第1份（驻留）
convert_to_xml()    → 构建完整 ET 树        ← 第2份
ET.tostring()       → xml_str 字符串        ← 第3份
minidom.parseString → 重新解析 xml_str      ← 第4份（最大放大点）
toprettyxml()       → pretty_xml 字符串
写文件 → 释放
```

10 万条 RIS 文件约 300 MB，峰值内存可达 **1~2 GB**。

**直接修复**（改动 3 行）：  
用 `ET.indent(root)` 替换 `minidom.parseString(ET.tostring(...)).toprettyxml()`，消除第 3、4 份冗余拷贝。需 Python 3.9+（已满足）。

```python
# 当前（parser.py 约 980 行）
xml_str = ET.tostring(root, encoding='unicode')
pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")
lines = [line for line in pretty_xml.split('\n') if line.strip()]
pretty_xml = '\n'.join(lines)
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(pretty_xml)

# 替换为
ET.indent(root, space="  ")
tree = ET.ElementTree(root)
tree.write(output_path, encoding='unicode', xml_declaration=False)
```

---

### 🔴 P0：_generate_split_xmls 持有全量 list 同时写文件

**位置**：`core/executors/handlers/parse_handler.py` → `_generate_split_xmls()`

**问题**：`all_entries`（全量 list）传入函数后，在写 N 个单篇 XML 过程中始终驻留。  
**修复方向**：流式处理——解析完一条立即写单篇 XML，不攒全量 list。

---

### 🟡 P1：ai_screen_handler 一次性把所有文献读入内存

**位置**：`core/executors/handlers/ai_screen_handler.py` → `execute()` 约 130 行

**问题**：
```python
entries_to_process = []
for df in input_files:
    entry = self._parse_xml_entry(df.file.path)  # 读文件内容到 dict
    entries_to_process.append(entry)             # 全量 list 驻留
```
10 万篇 × 每篇 ~1 KB abstract = **~100 MB** 字典列表。16 并发线程时各自持有引用，合计更高。

**修复方向**：改为懒加载 iterator，每个 batch 时才读该批文件：
```python
def _iter_entries(self, input_files):
    for df in input_files:
        if df.filename in processed_sources:
            continue
        entry = self._parse_xml_entry(df.file.path)
        entry["source_xml"] = df.filename
        entry["datafile_id"] = df.id
        yield entry
```
内存从 O(n) 降为 O(batch_size)。

---

### 🟡 P1：Celery Worker 无内存上限，OOM 直接杀进程

**位置**：`start.sh` → Celery 启动命令

**问题**：`celery worker -P threads -c 16` 无内存防护，任务内存泄漏会累积，最终被 OOM Killer 直接终止。

**修复**：添加 `--max-memory-per-child` 和 `--max-tasks-per-child`：
```bash
celery -A platform_backend worker \
  --loglevel=info -P threads -c 16 \
  --max-memory-per-child=512000 \   # 512MB 超限自动重启 worker（threads 模式下为近似值）
  --max-tasks-per-child=50          # 每处理 50 个任务重启一次，防止内存碎片积累
```

---

### 🟡 P1：Django 未配置文件上传内存限制

**位置**：`platform_backend/settings.py`（当前无相关配置）

**问题**：Django 默认 2.5 MB 以下用 `InMemoryUploadedFile`（全部驻留内存）。  
大 RIS/XML 文件上传时，Django worker 进程会持有完整文件内容直到请求结束。

**修复**（2 行）：
```python
# settings.py
FILE_UPLOAD_MAX_MEMORY_SIZE = 1 * 1024 * 1024   # 超过 1MB 走磁盘临时文件
DATA_UPLOAD_MAX_MEMORY_SIZE = 1 * 1024 * 1024   # 表单数据同样限制
```

---

### 🟢 P2：Gunicorn workers=4 在内存紧张服务器上会叠加

**位置**：`start.sh` → Gunicorn 启动命令

**问题**：fork 模式下 4 个 worker 各自独立进程，同时处理大文件任务时内存叠加。

**修复**：服务器内存 ≤ 4 GB 时改为 `--workers 2`，并加定期重启防内存碎片：
```bash
gunicorn platform_backend.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 2 \           # 根据服务器内存调整（建议 = CPU核数/2，最少2）
  --threads 2 \
  --timeout 300 \
  --max-requests 200 \    # 每个 worker 处理 200 个请求后重启
  --max-requests-jitter 20
```

---

### 💡 P2（长期）：解析全链路流式化

**目标**：彻底消除"全量 entries list"，改为 generator pipeline：

```
parse_file() → yield entry → 立即写单篇 XML → 写 merged XML（追加模式）
```

内存峰值从 O(n) 降为 O(1)，无论多大的文件都只占用单条条目的内存。  
改动较大，需重构 `parser.py` 的 `parse_directory` 和 `convert_to_xml`，以及 `parse_handler.py` 的 `execute()`。

---

## 优先级汇总

| 优先级 | 位置 | 改动量 | 预期效果 |
|--------|------|--------|----------|
| ⭐ P0 | `parser.py`：minidom → ET.indent | 5 行 | 解析内存减半 |
| ⭐ P0 | `settings.py`：文件上传内存限制 | 2 行 | 上传不占 worker 内存 |
| 🔧 P1 | `start.sh`：Celery max-memory-per-child | 2 行配置 | OOM 变重启，不停服 |
| 🔧 P1 | `ai_screen_handler.py`：懒加载 entries | ~20 行 | 筛选阶段内存 O(n)→O(1) |
| 🔧 P1 | `start.sh`：Gunicorn workers 调整 | 2 行 | 减少多 worker 内存叠加 |
| 💡 P2 | `parser.py` + `parse_handler.py`：全链路流式 | 较大 | 根治解析内存问题 |
