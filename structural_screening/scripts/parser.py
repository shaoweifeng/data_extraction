"""
文献解析脚本 - 纯净版

提供四种格式的解析函数：
- parse_ris(): RIS 格式（EndNote）
- parse_bib(): BibTeX 格式
- parse_nbib(): NBIB 格式（PubMed）
- parse_xml(): XML 格式

设计原则：
- 纯函数式，无副作用
- 无数据库操作
- 无文件系统假设（由调用者传入路径）
- 返回标准化的字典列表
"""

import os
import re
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from xml.dom import minidom

try:
    import rispy
except ImportError:
    rispy = None

try:
    import bibtexparser
except ImportError:
    bibtexparser = None


# ============================================================================
# RIS 格式解析
# ============================================================================

def parse_ris(file_path: str) -> List[Dict]:
    """
    解析RIS格式文献
    
    Args:
        file_path: RIS文件路径
    
    Returns:
        标准化的文献字典列表
    """
    if rispy is None:
        raise ImportError("rispy 未安装，请运行: pip install rispy")
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        entries = rispy.load(f)
    
    def first_value(d, keys):
        """获取第一个非空值"""
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, (int, float)):
                return str(v)
        return None
    
    parsed_entries = []
    for i, entry in enumerate(entries, start=1):
        # 提取URL（多来源尝试）
        url = entry.get('url') or entry.get('urls')
        if isinstance(url, list) and url:
            url = url[0]
        if not url:
            url = entry.get('UR') or entry.get('L1')
        
        # 提取页码
        pages = first_value(entry, ['pages'])
        start_page = first_value(entry, ['start_page', 'sp', 'SP'])
        end_page = first_value(entry, ['end_page', 'ep', 'EP'])
        page = pages
        if not page:
            if start_page and end_page:
                page = f"{start_page}-{end_page}"
            elif start_page:
                page = start_page
            elif end_page:
                page = end_page
        
        # 提取日期
        date = first_value(entry, ['date', 'publication_date', 'DA', 'Y1'])
        
        # 提取DOI
        doi = entry.get('doi') or entry.get('DO')
        if isinstance(doi, list):
            doi = doi[0] if doi else None
        
        parsed_entries.append({
            'title': entry.get('title') or entry.get('primary_title'),
            'authors': entry.get('authors', []),
            'journal': entry.get('journal_name') or entry.get('secondary_title'),
            'year': entry.get('year'),
            'volume': first_value(entry, ['volume', 'VL']),
            'issue': first_value(entry, ['number', 'issue', 'IS']),
            'page': page,
            'date': date,
            'doi': doi,
            'pmcid': first_value(entry, ['pmcid', 'PMCID']),
            'abstract': entry.get('abstract'),
            'url': url,
            'address': first_value(entry, ['address', 'AD']),
            'reference_type': first_value(entry, ['type_of_reference', 'type', 'TY']),
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'source_type': 'RIS'
        })
    
    return parsed_entries


# ============================================================================
# BibTeX 格式解析
# ============================================================================

def parse_bib(file_path: str) -> List[Dict]:
    """
    解析BibTeX格式文献
    
    Args:
        file_path: BibTeX文件路径
    
    Returns:
        标准化的文献字典列表
    """
    if bibtexparser is None:
        raise ImportError("bibtexparser 未安装，请运行: pip install bibtexparser")
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        library = bibtexparser.load(f)
    
    parsed_entries = []
    for i, entry in enumerate(library.entries, start=1):
        # 解析作者列表
        authors = entry.get('author', '').replace('\n', ' ').split(' and ')
        authors = [a.strip() for a in authors if a.strip()]
        
        # 提取URL
        url = entry.get('url') or entry.get('link') or entry.get('URL')
        
        # 构建日期
        year = entry.get('year')
        month = entry.get('month')
        date = None
        if month and year:
            date = f"{month} {year}"
        elif year:
            date = str(year)
        
        parsed_entries.append({
            'title': entry.get('title'),
            'authors': authors,
            'journal': entry.get('journal'),
            'year': year,
            'volume': entry.get('volume'),
            'issue': entry.get('number') or entry.get('issue'),
            'page': entry.get('pages'),
            'date': date,
            'doi': entry.get('doi'),
            'pmcid': entry.get('pmcid') or entry.get('PMCID'),
            'abstract': entry.get('abstract'),
            'url': url,
            'address': entry.get('address'),
            'reference_type': entry.get('ENTRYTYPE') or entry.get('type'),
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'source_type': 'BIB'
        })
    
    return parsed_entries


# ============================================================================
# NBIB 格式解析（PubMed）
# ============================================================================

def parse_nbib(file_path: str) -> List[Dict]:
    """
    解析NBIB/Medline格式文献（PubMed导出）
    
    Args:
        file_path: NBIB文件路径
    
    Returns:
        标准化的文献字典列表
    """
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    entries = []
    current_entry = {}
    current_key = None
    current_value = []
    
    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        
        # 续行（以4个空格开头）
        if line[:4] == '    ' and current_key:
            current_value.append(line.strip())
        else:
            # 保存上一个键值对
            if current_key:
                val = ' '.join(current_value)
                if current_key in current_entry:
                    if isinstance(current_entry[current_key], list):
                        current_entry[current_key].append(val)
                    else:
                        current_entry[current_key] = [current_entry[current_key], val]
                else:
                    current_entry[current_key] = val
            
            # 新键值对（格式：TI  - 标题）
            if '-' in line[:5]:
                parts = line.split('-', 1)
                current_key = parts[0].strip()
                current_value = [parts[1].strip()] if len(parts) > 1 else []
            else:
                current_key = None
    
    # 添加最后一个条目
    if current_entry:
        entries.append(current_entry)
    
    # 重新解析以分割多个记录（按PMID分隔）
    records = []
    current_record = {}
    
    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        
        if line.startswith('PMID-'):
            if current_record:
                # 从PMID构建URL
                if 'url' not in current_record and 'PMID' in current_record:
                    pmid = current_record['PMID'].split()[0] if current_record['PMID'] else ''
                    current_record['url'] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"
                records.append(current_record)
                current_record = {}
            
            # 提取PMID
            current_record['PMID'] = line.split('-', 1)[1].strip()
            current_key = 'PMID'
            current_value = []
        elif line[:4] == '    ' and current_key:
            current_value.append(line.strip())
        elif '-' in line[:5]:
            if current_key and current_value:
                val = ' '.join(current_value)
                if current_key in current_record:
                    if isinstance(current_record[current_key], list):
                        current_record[current_key].append(val)
                    else:
                        current_record[current_key] = [current_record[current_key], val]
                else:
                    current_record[current_key] = val
            
            parts = line.split('-', 1)
            current_key = parts[0].strip()
            current_value = [parts[1].strip()] if len(parts) > 1 else []
    
    if current_record:
        records.append(current_record)
    
    # 标准化输出
    def get_first(d, keys):
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, list):
                return v[0] if v else None
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None
    
    parsed_entries = []
    for i, record in enumerate(records, start=1):
        # 提取作者列表
        authors = record.get('AU') or record.get('FAU') or []
        if isinstance(authors, str):
            authors = [authors]
        
        # 提取DOI
        doi = get_first(record, ['AID', 'LID', 'doi'])
        if doi and '[doi]' in doi:
            doi = doi.replace('[doi]', '').strip()
        
        # 提取URL
        url = get_first(record, ['url', 'URL', 'AID'])
        if not url:
            pmid = get_first(record, ['PMID'])
            if pmid:
                url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid.split()[0]}"
        
        parsed_entries.append({
            'title': get_first(record, ['TI', 'BTI']),
            'authors': authors,
            'journal': get_first(record, ['JT', 'TA']),
            'year': get_first(record, ['YR', 'DP']),
            'volume': get_first(record, ['VI']),
            'issue': get_first(record, ['IP']),
            'page': get_first(record, ['PG']),
            'date': get_first(record, ['DP', 'EDAT']),
            'doi': doi,
            'pmcid': get_first(record, ['PMCID']),
            'abstract': get_first(record, ['AB']),
            'url': url,
            'address': get_first(record, ['AD']),
            'reference_type': get_first(record, ['PT']),
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'source_type': 'NBIB'
        })
    
    return parsed_entries


# ============================================================================
# XML 格式解析
# ============================================================================

def parse_xml(file_path: str) -> List[Dict]:
    """
    解析XML格式文献
    
    支持两种格式：
    1. EndNote XML（<xml><records><record>...）— 最常见的文献管理导出格式
    2. Reference XML（<references><reference>...）— 统一内部格式
    
    Args:
        file_path: XML文件路径
    
    Returns:
        标准化的文献字典列表
    """
    def itext(elem):
        if elem is None:
            return ""
        return "".join(elem.itertext()).strip()

    def first_text(parent, paths):
        for p in paths:
            e = parent.find(p)
            t = itext(e)
            if t:
                return t
        return ""

    tree = ET.parse(file_path)
    root = tree.getroot()

    # ========== EndNote XML 格式 ==========
    records_node = root.find("./records")
    if root.tag == "xml" and records_node is not None:
        parsed_entries = []
        for i, rec in enumerate(records_node.findall("./record"), start=1):
            title = first_text(rec, ["./titles/title"])
            journal = first_text(rec, ["./titles/secondary-title", "./periodical/full-title"])
            year_raw = first_text(rec, ["./dates/year", "./pub-dates/year", "./dates/pub-dates/year"])
            year_match = re.search(r"\b(19|20)\d{2}\b", year_raw)
            year = year_match.group(0) if year_match else (year_raw[:4] if year_raw else "")
            reference_type = ""
            rt = rec.find("./ref-type")
            if rt is not None:
                reference_type = rt.get("name") or ""
            volume = first_text(rec, ["./volume"])
            issue = first_text(rec, ["./number"])
            page = first_text(rec, ["./pages"])
            date = first_text(rec, ["./dates/pub-dates/date", "./pub-dates/date", "./dates/date"])
            if year and date and year not in date:
                date = f"{date} {year}"
            address = first_text(rec, ["./auth-address"])
            pmcid = first_text(rec, ["./custom2"])

            authors = []
            for a in rec.findall("./contributors/authors/author"):
                t = itext(a)
                if t:
                    authors.append(t)

            abstract = first_text(rec, ["./abstract"])

            doi_raw = first_text(rec, ["./doi", "./electronic-resource-num"])
            doi_raw = doi_raw.replace("doi:", "").replace("DOI:", "").strip()
            doi = doi_raw.split()[0] if doi_raw else ""
            doi = doi.strip().rstrip(".").rstrip(";").strip()

            accession = first_text(rec, ["./accession-num"])
            accession = accession.strip()

            wos_id = ""
            if accession.upper().startswith("WOS:"):
                wos_id = accession
            else:
                m = re.search(r"\bWOS:\w+\b", accession)
                if m:
                    wos_id = m.group(0)

            url = ""
            if accession.isdigit():
                url = f"https://pubmed.ncbi.nlm.nih.gov/{accession}/"
            elif doi:
                url = f"https://doi.org/{doi}"
            elif wos_id:
                url = f"https://www.webofscience.com/wos/woscc/full-record/{wos_id}"

            parsed_entries.append({
                'title': title,
                'authors': authors,
                'journal': journal,
                'year': year,
                'reference_type': reference_type,
                'volume': volume,
                'issue': issue,
                'page': page,
                'date': date,
                'pmcid': pmcid,
                'address': address,
                'abstract': abstract,
                'doi': doi,
                'url': url,
                'source_file': os.path.basename(file_path),
                'source_position': i,
                'record_number': first_text(rec, ["./rec-number"]),
                'type': 'XML'
            })
        return parsed_entries

    # ========== Reference XML 格式（内部统一格式）==========
    parsed_entries = []
    for i, ref in enumerate(root.findall(".//Reference"), start=1):
        title = first_text(ref, ["Title"])
        authors = []
        for a in ref.findall("./Authors/Author"):
            t = itext(a)
            if t:
                authors.append(t)
        journal = first_text(ref, ["Journal"])
        year = first_text(ref, ["Year"])
        abstract = first_text(ref, ["Abstract"])
        doi = first_text(ref, ["DOI"])
        url = first_text(ref, ["URL"])
        parsed_entries.append({
            'title': title,
            'authors': authors,
            'journal': journal,
            'year': year,
            'abstract': abstract,
            'doi': doi,
            'url': url,
            'source_file': os.path.basename(file_path),
            'source_position': i,
            'type': 'XML'
        })
    return parsed_entries


# ============================================================================
# CIW 格式解析（Web of Science）
# ============================================================================

def parse_ciw(file_path: str) -> List[Dict]:
    """
    解析 CIW 格式文献（Web of Science 导出格式）
    
    CIW 格式特点：
    - 字段标签：TI, AU, AF, SO, PY, PT, VL, IS, BP, EP, PD, C1, DI, AB, PM, UT, UR, ER
    - 多值字段：AU, AF, C1（每行一个值）
    - 续行：以两个空格开头
    - 记录分隔：ER
    
    Args:
        file_path: CIW 文件路径
    
    Returns:
        标准化的文献字典列表
    """
    def clean(s):
        return (s or "").strip()
    
    def add_to_field(d, key, value):
        if key not in d:
            d[key] = []
        d[key].append(value)
    
    records = []
    current = {}
    current_tag = None
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            
            # 记录结束
            if line.strip() == "ER":
                if current:
                    records.append(current)
                current = {}
                current_tag = None
                continue
            
            # 续行（以两个空格开头）
            if line.startswith("  ") and current_tag:
                add_to_field(current, current_tag, clean(line))
                continue
            
            # 新字段（格式：XX value，XX是两个字符的标签）
            if len(line) >= 3 and line[2] == " ":
                tag = line[:2]
                value = clean(line[3:])
                current_tag = tag
                if value:
                    add_to_field(current, tag, value)
                continue
    
    # 处理最后一条记录
    if current:
        records.append(current)
    
    parsed_entries = []
    for i, rec in enumerate(records, start=1):
        # 标题（TI 字段）
        title = " ".join(rec.get("TI", [])).strip()
        if not title:
            continue
        
        # 作者（AU 优先，AF 备用）
        authors = [a for a in rec.get("AU", []) if a] or [a for a in rec.get("AF", []) if a]
        
        # 期刊（SO 字段）
        journal = " ".join(rec.get("SO", [])).strip()
        
        # 年份（PY 字段）
        year = ""
        if rec.get("PY"):
            year = clean(rec.get("PY", [""])[0])
        
        # 文献类型（PT 字段）
        reference_type = clean(rec.get("PT", [""])[0]) if rec.get("PT") else ""
        
        # 卷、期、页码
        volume = clean(rec.get("VL", [""])[0]) if rec.get("VL") else ""
        issue = clean(rec.get("IS", [""])[0]) if rec.get("IS") else ""
        bp = clean(rec.get("BP", [""])[0]) if rec.get("BP") else ""
        ep = clean(rec.get("EP", [""])[0]) if rec.get("EP") else ""
        page = ""
        if bp and ep:
            page = f"{bp}-{ep}"
        elif bp:
            page = bp
        elif ep:
            page = ep
        
        # 日期（PD 字段）
        date = clean(rec.get("PD", [""])[0]) if rec.get("PD") else ""
        
        # 地址（C1 字段，多值）
        address = "; ".join([a for a in rec.get("C1", []) if a]).strip()
        
        # DOI（DI 字段）
        doi = ""
        if rec.get("DI"):
            doi = clean(rec.get("DI", [""])[0]).rstrip(".").rstrip(";").strip()
        
        # 摘要（AB 字段）
        abstract = " ".join(rec.get("AB", [])).strip()
        
        # PMID（PM 字段）
        pmid = clean(rec.get("PM", [""])[0]) if rec.get("PM") else ""
        
        # UT（WoS 记录号）
        ut = clean(rec.get("UT", [""])[0]) if rec.get("UT") else ""
        
        # UR（URL）
        ur = ""
        if rec.get("UR"):
            ur = clean(rec.get("UR", [""])[0])
        
        # 构建URL（优先级：UR > DOI > PMID > UT）
        url = ""
        if ur.lower().startswith("http://") or ur.lower().startswith("https://"):
            url = ur
        elif doi:
            url = f"https://doi.org/{doi}"
        elif pmid.isdigit():
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        elif ut:
            url = f"https://www.webofscience.com/wos/woscc/full-record/{ut}"
        
        parsed_entries.append({
            "title": title,
            "authors": authors,
            "journal": journal,
            "year": year,
            "reference_type": reference_type,
            "volume": volume,
            "issue": issue,
            "page": page,
            "date": date,
            "address": address,
            "doi": doi,
            "abstract": abstract,
            "pmcid": "",
            "url": url,
            "source_file": os.path.basename(file_path),
            "source_position": i,
            "record_number": ut,
            "source_type": "CIW"
        })
    
    return parsed_entries


# ============================================================================
# 自动选择解析器
# ============================================================================

def parse_file(file_path: str) -> List[Dict]:
    """
    根据文件扩展名自动选择解析器
    
    Args:
        file_path: 文件路径
    
    Returns:
        标准化的文献字典列表
    
    Raises:
        ValueError: 不支持的文件格式
    
    支持格式：
    - .ris: RIS 格式（使用 rispy 库）
    - .ciw: CIW 格式（Web of Science 导出，手动解析）
    - .bib, .bibtex: BibTeX 格式
    - .nbib, .medline: NBIB 格式（PubMed）
    - .xml: XML 格式
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.ris':
        return parse_ris(file_path)
    elif ext == '.ciw':  # CIW 格式需要专门的解析器
        return parse_ciw(file_path)
    elif ext in ['.bib', '.bibtex']:
        return parse_bib(file_path)
    elif ext in ['.nbib', '.medline']:
        return parse_nbib(file_path)
    elif ext == '.xml':
        return parse_xml(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def parse_directory(dir_path: str) -> List[Dict]:
    """
    解析目录中所有支持的文献文件
    
    Args:
        dir_path: 目录路径
    
    Returns:
        合并后的文献字典列表
    """
    all_entries = []
    
    for filename in os.listdir(dir_path):
        file_path = os.path.join(dir_path, filename)
        
        if not os.path.isfile(file_path):
            continue
        
        try:
            entries = parse_file(file_path)
            all_entries.extend(entries)
        except Exception as e:
            print(f"[警告] 解析失败 {filename}: {e}")
    
    return all_entries


# ============================================================================
# XML 输出函数
# ============================================================================

def convert_to_xml(entries: List[Dict], output_path: str) -> None:
    """
    将文献条目转换为统一XML格式
    
    Args:
        entries: 文献字典列表
        output_path: 输出文件路径
    """
    root = ET.Element('references')
    
    for entry in entries:
        ref_elem = ET.SubElement(root, 'reference')
        
        # 标题
        if entry.get('title'):
            title_elem = ET.SubElement(ref_elem, 'Title')
            title_elem.text = entry['title']
        
        # 作者
        authors = entry.get('authors', [])
        if authors:
            authors_elem = ET.SubElement(ref_elem, 'Authors')
            for author in authors:
                author_elem = ET.SubElement(authors_elem, 'Author')
                author_elem.text = author
        
        # 年份
        if entry.get('year'):
            year_elem = ET.SubElement(ref_elem, 'Year')
            year_elem.text = str(entry['year'])
        
        # 期刊
        if entry.get('journal'):
            journal_elem = ET.SubElement(ref_elem, 'Journal')
            journal_elem.text = entry['journal']
        
        # 摘要
        if entry.get('abstract'):
            abstract_elem = ET.SubElement(ref_elem, 'Abstract')
            abstract_elem.text = entry['abstract']
        
        # DOI
        if entry.get('doi'):
            doi_elem = ET.SubElement(ref_elem, 'DOI')
            doi_elem.text = entry['doi']
        
        # URL
        if entry.get('url'):
            url_elem = ET.SubElement(ref_elem, 'URL')
            url_elem.text = entry['url']
        
        # 其他字段
        for key in ['volume', 'issue', 'page', 'date', 'pmcid', 'address']:
            if entry.get(key):
                elem = ET.SubElement(ref_elem, key.capitalize())
                elem.text = str(entry[key])
    
    # 格式化输出
    xml_str = ET.tostring(root, encoding='unicode')
    pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")
    
    # 移除空行
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    pretty_xml = '\n'.join(lines)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(pretty_xml)


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


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python parser.py <文件或目录路径>")
        sys.exit(1)
    
    path = sys.argv[1]
    
    if os.path.isfile(path):
        entries = parse_file(path)
    elif os.path.isdir(path):
        entries = parse_directory(path)
    else:
        print(f"错误: 路径不存在 {path}")
        sys.exit(1)
    
    print(f"成功解析 {len(entries)} 条文献")
    
    # 打印前3条示例
    for i, entry in enumerate(entries[:3], 1):
        print(f"\n{i}. {entry.get('title', 'N/A')}")
        print(f"   作者: {', '.join(entry.get('authors', ['N/A']))}")
        print(f"   年份: {entry.get('year', 'N/A')}")
