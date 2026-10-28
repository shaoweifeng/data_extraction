"""One QA read adapter; shared assets never impersonate a QA one-to-one row."""
from django.core.exceptions import ObjectDoesNotExist


def asset_for_qa(reference):
    if getattr(reference, 'shared_fulltext_asset_id', None):
        asset = reference.shared_fulltext_asset
        if asset.project_id != reference.project_id:
            raise ValueError('共享全文与质量评价文献不属于同一项目。')
        return asset
    try:
        asset = getattr(reference, 'fulltext_asset', None)
    except ObjectDoesNotExist:
        return None
    if asset and (asset.project_id != reference.project_id or asset.qa_reference_id != reference.id):
        raise ValueError('全文与质量评价文献不匹配。')
    return asset


def download_url_for_qa(reference, asset):
    if getattr(reference, 'shared_fulltext_asset_id', None):
        return f'/api/fulltext/assets/{asset.pk}/download/'
    return f'/api/qa/fulltext-assets/{asset.pk}/download/'


def process_for_qa(reference):
    if getattr(reference, 'shared_fulltext_asset_id', None):
        from core.fulltext.processing import process_asset
        return process_asset(reference.shared_fulltext_asset_id)
    from core.quality.services.fulltext import process_fulltext_asset
    return process_fulltext_asset(reference.fulltext_asset.pk)
