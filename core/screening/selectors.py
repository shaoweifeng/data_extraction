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

    return {
        'abstract': text('Abstract'),
        'url': text('Url') or text('URL') or text('url'),
        'doi': text('Doi') or text('DOI'),
    }


def load_xml_fields_bulk(source_xmls, project_id) -> dict:
    """Resolve and parse many source XML files with one directory scan."""
    import re
    from django.conf import settings as django_settings

    requested = [source for source in source_xmls if source]
    if not requested:
        return {}

    project_dir = Path(django_settings.MEDIA_ROOT) / 'projects' / f'project_{project_id}'
    candidates = list(project_dir.rglob('*.xml')) if project_dir.exists() else []
    by_name = {path.name: path for path in candidates}
    resolved = {}
    for source in requested:
        direct = Path(source)
        if direct.exists():
            resolved[source] = direct
            continue
        name = direct.name
        match = by_name.get(name)
        if match is None:
            prefix_match = re.match(r'^(\d+_)', name)
            prefix = prefix_match.group(1) if prefix_match else name
            match = next((path for path in candidates if path.name.startswith(prefix)), None)
        if match is not None:
            resolved[source] = match

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
