"""Replaceable malware-scanning boundary for private PDF assets."""

from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class ScanResult:
    status: str
    detail: str = ''


class DisabledScanner:
    """Explicit no-op used until ClamAV or a cloud scanner is configured."""

    def scan(self, file_path):
        return ScanResult('not_configured')


def scan_pdf(file_path):
    scanner_class = import_string(settings.QA_MALWARE_SCANNER_BACKEND)
    result = scanner_class().scan(file_path)
    if result.status not in {'clean', 'not_configured', 'infected', 'failed'}:
        raise ValueError('扫描器返回了不支持的状态')
    return result
