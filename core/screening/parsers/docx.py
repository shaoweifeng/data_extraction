"""Word-wrapped EndNote tagged-text parser."""

import os
from typing import Dict, List

from .enw import _parse_procite_text


def parse_docx(file_path: str) -> List[Dict]:
    """
    解析 .doc / .docx 文件中的 EndNote Tagged 格式内容。
    文件内容按 ProCite/EndNode Tagged 格式组织（与 .enw/.txt 相同），
    每个段落可能包含一整条记录（段落内用 \r\n 分隔各字段行），
    也可能是普通空段落分隔符。
    """
    try:
        import docx as _docx
    except ImportError:
        raise ImportError(
            "解析 .doc/.docx 需要安装 python-docx：pip install python-docx"
        )

    doc = _docx.Document(file_path)
    lines = []
    for para in doc.paragraphs:
        text = para.text
        # 段落内部可能用 \r\n 连接多个字段行（SinoMed 导出格式）
        for sub in text.splitlines():
            lines.append(sub)
        # 段落之间加一个空行作为记录分隔符（若段落本身为空则自然产生空行）
        if text.strip():
            lines.append('')  # 在非空段落后补一个空行，确保记录边界

    full_text = '\n'.join(lines)
    entries = _parse_procite_text(full_text)
    for i, e in enumerate(entries, 1):
        e['source_file'] = os.path.basename(file_path)
        e['source_position'] = i
    return entries
