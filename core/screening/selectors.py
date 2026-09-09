"""初筛结果和原始文献的只读查询。"""

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from core.models import DataFile, StageStep
from core.artifacts.types import ArtifactType


logger = logging.getLogger(__name__)


def _parse_xml_summary(path: Path) -> dict:
    root = ET.parse(path).getroot()
    ref = root
    if root.tag not in ('Reference', 'reference'):
        ref = root.find('.//Reference') or root.find('.//reference') or root

    def text(tag):
        elem = ref.find(tag)
        return ''.join(elem.itertext()).strip() if elem is not None else ''

    # 人工审阅只使用 abstract/url/doi；导出复用同一批量定位能力并需要完整字段。
    return {
        'ReferenceType': text('ReferenceType'),
        'Title': text('Title'),
        'Author': text('Authors') or text('Author'),
        'Year': text('Year'),
        'Journal': text('Journal'),
        'Volume': text('Volume'),
        'Issue': text('Issue'),
        'Page': text('Page'),
        'Date': text('Date'),
        'Doi': text('Doi') or text('DOI'),
        'PMCID': text('PMCID'),
        'Abstract': text('Abstract'),
        'URL': text('Url') or text('URL') or text('url'),
        'Address': text('Address'),
        'abstract': text('Abstract'),
        'url': text('Url') or text('URL') or text('url'),
        'doi': text('Doi') or text('DOI'),
    }


def load_xml_fields_bulk(source_xmls, project_id) -> dict:
    """Resolve and parse the requested XML files without scanning the project tree."""
    requested = [source for source in source_xmls if source]
    if not requested:
        return {}

    resolved = {}
    unresolved_names = set()
    for source in requested:
        direct = Path(source)
        if direct.exists():
            resolved[source] = direct
            continue
        unresolved_names.add(direct.name)

    # source_xml 通常只保存文件名。通过 DataFile 精确定位当前页文件，避免每次
    # 请求都 rglob 项目下数万份 XML。若同名文件存在，优先使用最新记录。
    if unresolved_names:
        candidates = (
            DataFile.objects.filter(project_id=project_id, filename__in=unresolved_names)
            .exclude(file='')
            .order_by('-id')
            .only('filename', 'file')
        )
        by_name = {}
        for data_file in candidates:
            by_name.setdefault(data_file.filename, data_file)
        for source in requested:
            if source in resolved:
                continue
            data_file = by_name.get(Path(source).name)
            if data_file is not None:
                try:
                    resolved[source] = Path(data_file.file.path)
                except (NotImplementedError, ValueError):
                    logger.debug('[review] 文件存储不支持本地路径: %s', data_file.file.name)

    fields = {}
    for source, path in resolved.items():
        try:
            fields[source] = _parse_xml_summary(path)
        except (OSError, ET.ParseError) as exc:
            logger.debug('[review] 读取 XML 字段失败 %s: %s', path, exc)
            fields[source] = {}
    return fields


def load_xml_fields(source_xml: str, project_id) -> dict:
    """Compatibility helper for single-source callers."""
    return load_xml_fields_bulk([source_xml], project_id).get(source_xml, {})


def ai_result_files(project_id, ai_step):
    """返回 ai_screen 输出的所有结果文件列表（DataFile QuerySet）。"""
    return DataFile.objects.filter(
        project_id=project_id,
        step=ai_step,
        data_category='output',
        metadata__artifact_type=ArtifactType.SCREENING_RESULT_JSON,
    )


def load_ai_results(project_id):
    """
    加载文献列表。优先从 ai_screen 结果 JSON 读取；
    若 ai_screen 未执行，则从去重后 XML 文件中读取基础信息（title/source_xml），
    使人工审阅步骤可独立于 AI 初筛运作。
    """
    from core.models import StageStep
    ai_step = StageStep.objects.filter(
        stage__project_id=project_id,
        step_key='ai_screen',
    ).order_by('-id').first()

    if ai_step:
        result_files = ai_result_files(project_id, ai_step)
        if result_files.exists():
            results = []
            for df in result_files:
                try:
                    with open(df.file.path, 'r', encoding='utf-8') as f:
                        results.append(json.load(f))
                except Exception as e:
                    logger.warning(f"[review] 读取结果文件失败 {df.filename}: {e}")
            if results:
                return results

    # ── 降级：从去重后 XML 文件读取基础信息 ──
    return load_refs_from_xml(project_id)


def load_ai_result_file(data_file) -> dict:
    """Load one result file, falling back to its indexed metadata if unreadable."""
    try:
        with data_file.file.open('r') as result_file:
            return json.load(result_file)
    except Exception as exc:
        logger.warning('[review] 读取结果文件失败 %s: %s', data_file.filename, exc)
        return dict(data_file.metadata or {})


def load_ai_results_by_source(project_id, source_xmls) -> dict:
    """Load only the requested AI result files, keyed by source XML name."""
    requested = {source for source in source_xmls if source}
    if not requested:
        return {}

    ai_step = StageStep.objects.filter(
        stage__project_id=project_id,
        step_key='ai_screen',
    ).order_by('-id').first()
    if ai_step:
        result_files = ai_result_files(project_id, ai_step).filter(
            metadata__source_xml__in=requested,
        )
        indexed = {}
        for data_file in result_files:
            result = load_ai_result_file(data_file)
            source_xml = result.get('source_xml') or (data_file.metadata or {}).get('source_xml')
            if source_xml:
                indexed[source_xml] = result
        if indexed:
            return indexed

    # Compatibility for legacy result rows that predate the metadata index.
    return {
        result.get('source_xml', ''): result
        for result in load_ai_results(project_id)
        if result.get('source_xml') in requested
    }


def load_refs_from_xml(project_id):
    """
    AI 初筛未完成时，从 dedup 步骤输出的 XML 文件中读取文献基础信息，
    以支持人工审阅独立运作。
    返回结构与 AI 结果 JSON 兼容（decision/include_or_not 留空）。
    """
    import xml.etree.ElementTree as ET
    from core.models import DataFile, StageStep

    dedup_step = StageStep.objects.filter(
        stage__project_id=project_id,
        step_key='dedup',
    ).order_by('-id').first()

    xml_files = DataFile.objects.filter(
        project_id=project_id,
        metadata__artifact_type=ArtifactType.SCREENING_DEDUP_REFERENCE_XML,
    )
    if dedup_step:
        xml_files = xml_files.filter(step=dedup_step)

    results = []
    for df in xml_files:
        if not df.file or not df.filename.endswith('.xml'):
            continue
        try:
            root = ET.parse(df.file.path).getroot()
            ref = root
            if root.tag not in ("Reference", "reference"):
                ref = root.find(".//Reference") or root.find(".//reference") or root

            def _t(tag):
                el = ref.find(tag)
                return ''.join(el.itertext()).strip() if el is not None else ''

            results.append({
                'source_xml':      df.file.path,
                'title':           _t('Title'),
                'authors':         _t('Authors') or _t('Author'),
                'year':            _t('Year'),
                'journal':         _t('Journal'),
                'doi':             _t('Doi') or _t('DOI'),
                'url':             _t('URL') or _t('Url') or _t('url'),
                'decision':        '',        # 无 AI 判断
                'include_or_not':  '',
                'exclusion_reason': '',
            })
        except Exception as e:
            logger.debug(f"[review] 解析 XML 失败 {df.filename}: {e}")

    return results
