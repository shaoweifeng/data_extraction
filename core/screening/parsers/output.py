"""Serialization helpers for normalized reference records."""

import os
import re
import xml.etree.ElementTree as ET
from typing import Callable, Dict, Iterable, List, Optional


def _reference_element(entry: Dict) -> ET.Element:
    """将单条标准化文献转为 XML 元素。"""
    ref_elem = ET.Element('reference')

    if entry.get('title'):
        ET.SubElement(ref_elem, 'Title').text = str(entry['title'])

    authors = entry.get('authors', [])
    if authors:
        authors_elem = ET.SubElement(ref_elem, 'Authors')
        if isinstance(authors, (list, tuple)):
            for author in authors:
                ET.SubElement(authors_elem, 'Author').text = str(author)
        else:
            authors_elem.text = str(authors)

    fields = [
        ('year', 'Year'),
        ('journal', 'Journal'),
        ('abstract', 'Abstract'),
        ('doi', 'Doi'),
        ('url', 'Url'),
        ('volume', 'Volume'),
        ('issue', 'Issue'),
        ('page', 'Page'),
        ('date', 'Date'),
        ('reference_type', 'ReferenceType'),
        ('pmcid', 'PMCID'),
        ('address', 'Address'),
    ]
    for field_key, xml_tag in fields:
        if entry.get(field_key):
            ET.SubElement(ref_elem, xml_tag).text = str(entry[field_key])
    return ref_elem


def convert_to_xml(entries: Iterable[Dict], output_path: str) -> None:
    """
    将文献条目转换为统一XML格式

    Args:
        entries: 文献字典列表
        output_path: 输出文件路径
    """
    write_xml_stream(entries, output_path)


def write_xml_stream(
    entries: Iterable[Dict],
    output_path: str,
    on_entry: Optional[Callable[[Dict, int], None]] = None,
) -> int:
    """Single-pass merged XML writer with an optional per-record sink."""
    count = 0
    with open(output_path, 'wb') as output:
        output.write(b'<?xml version="1.0" encoding="utf-8"?>\n<references>\n')
        for count, entry in enumerate(entries, start=1):
            payload = ET.tostring(_reference_element(entry), encoding='utf-8')
            output.write(b'  ')
            output.write(payload)
            output.write(b'\n')
            if on_entry is not None:
                on_entry(entry, count)
        output.write(b'</references>\n')
    return count


def split_to_single_files(entries: List[Dict], output_dir: str) -> int:
    """
    将文献条目拆分为单个XML文件

    Args:
        entries: 文献字典列表
        output_dir: 输出目录

    Returns:
        生成的文件数量
    """
    import hashlib

    os.makedirs(output_dir, exist_ok=True)

    count = 0
    for entry in entries:
        # 生成安全的文件名（标题 + hash）
        title = entry.get('title', 'unknown')[:50]
        safe_title = re.sub(r'[^\w\-]', '_', title)

        # 添加hash避免冲突
        hash_suffix = hashlib.md5(title.encode()).hexdigest()[:8]
        filename = f"{safe_title}_{hash_suffix}.xml"

        # 写入单篇XML
        convert_to_xml([entry], os.path.join(output_dir, filename))
        count += 1

    return count
