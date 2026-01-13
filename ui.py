import os
import sys
import threading
import subprocess
import importlib.util
import io
import contextlib
from flask import Flask, request, jsonify, render_template_string


def run_pipeline1(base_dir, force_reprocess):
    script_path = os.path.join(base_dir, "1", "1.py")
    if not os.path.exists(script_path):
        return False, "未找到 1/1.py"
    
    # 构建输入：选择1（增量）或 选择2+确认（全量）
    input_str = "2\nyes\n" if force_reprocess else "1\n"
    
    cmd = [sys.executable, "1.py"]
    cwd = os.path.join(base_dir, "1")
    
    try:
        # 使用 subprocess 调用，确保环境和路径正确
        # cwd 设置为 1/ 目录，解决导入 config 和相对路径问题
        r = subprocess.run(
            cmd,
            cwd=cwd,
            input=input_str,
            text=True,
            capture_output=True
        )
        
        output = r.stdout
        err = r.stderr
        msg = ""
        if output:
            msg += output
        if err:
            msg += f"\nErrors/Warnings:\n{err}"
            
        if r.returncode != 0:
            return False, f"执行失败 (代码 {r.returncode}):\n{msg}"
            
        return True, msg or "完成"
        
    except Exception as e:
        return False, f"调用子进程失败: {e}"


def run_pipeline2(base_dir):
    cmds = [
        [sys.executable, os.path.join(base_dir, "2", "standard.py")],
        [sys.executable, os.path.join(base_dir, "2", "excel.py")]
    ]
    combined = []
    for cmd in cmds:
        r = subprocess.run(cmd, cwd=base_dir, text=True, capture_output=True)
        combined.append("$ " + " ".join(cmd))
        if r.stdout:
            combined.append(r.stdout)
        if r.stderr:
            combined.append(r.stderr)
        if r.returncode != 0:
            return False, "\n".join(combined) + f"\n退出码: {r.returncode}"
    return True, "\n".join(combined) or "完成"


app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNING_LOCK = threading.Lock()

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>免疫文献提取工具 UI</title>
</head>
<body>
<h2>步骤 1：分析 PDF（目录 1）</h2>
<button onclick="run1(false)">增量处理（只处理新 PDF）</button>
<button onclick="run1(true)">强制重新处理所有 PDF</button>
<h2>步骤 2：标准化并导出 Excel（目录 2）</h2>
<button onclick="run2()">从结果生成 Excel</button>
<pre id="log" style="white-space:pre-wrap;border:1px solid #ccc;padding:8px;margin-top:12px;"></pre>
<script>
async function run1(force) {
  const btns = document.querySelectorAll('button'); btns.forEach(b=>b.disabled=true);
  document.getElementById('log').textContent = '正在执行...';
  try {
    const resp = await fetch('/run1?force='+(force?'1':'0'));
    const data = await resp.json();
    document.getElementById('log').textContent = data.message + "\\n\\n" + (data.output||'');
  } catch(e) {
    document.getElementById('log').textContent = '出错: '+e;
  } finally {
    btns.forEach(b=>b.disabled=false);
  }
}
async function run2() {
  const btns = document.querySelectorAll('button'); btns.forEach(b=>b.disabled=true);
  document.getElementById('log').textContent = '正在执行...';
  try {
    const resp = await fetch('/run2');
    const data = await resp.json();
    document.getElementById('log').textContent = data.message + "\\n\\n" + (data.output||'');
  } catch(e) {
    document.getElementById('log').textContent = '出错: '+e;
  } finally {
    btns.forEach(b=>b.disabled=false);
  }
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/run1")
def route_run1():
    force = request.args.get("force") == "1"
    if not RUNNING_LOCK.acquire(blocking=False):
        return jsonify({"message": "已有任务在运行", "output": ""})
    try:
        ok, msg = run_pipeline1(BASE_DIR, force)
        return jsonify({"message": "完成" if ok else "出错", "output": msg})
    finally:
        RUNNING_LOCK.release()


@app.route("/run2")
def route_run2():
    if not RUNNING_LOCK.acquire(blocking=False):
        return jsonify({"message": "已有任务在运行", "output": ""})
    try:
        ok, msg = run_pipeline2(BASE_DIR)
        return jsonify({"message": "完成" if ok else "出错", "output": msg})
    finally:
        RUNNING_LOCK.release()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000)
