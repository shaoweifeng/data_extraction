"""Word-wrapped EndNote tagged-text parser."""

import os
from typing import Dict, Iterator

from .enw import _iter_procite_lines


def parse_docx(file_path: str) -> Iterator[Dict]:
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
    def paragraph_lines():
        for para in doc.paragraphs:
            text = para.text
            # 直接把段落子行交给状态机，避免同时保留 lines/full_text/records。
            yield from text.splitlines()
            if text.strip():
                yield ''

    for i, entry in enumerate(_iter_procite_lines(paragraph_lines()), 1):
        entry['source_file'] = os.path.basename(file_path)
        entry['source_position'] = i
        yield entry
