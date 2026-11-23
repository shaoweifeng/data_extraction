"""Public lookup outcomes, independent from internal exception details."""
MESSAGES = {
    'identifier_missing': '缺少 DOI / PMID，无法精确查找，请手动上传全文。',
    'doi_missing': '缺少 DOI，此来源无法查找。',
    'identifier_mismatch': '来源返回的文献标识符不一致，已忽略。',
    'not_open_access': '此来源没有可用的开放全文。',
    'no_pdf_link': '来源未提供 PDF 链接。',
    'not_found': '未找到全文，可更换来源或手动上传。',
    'candidates_found': '已找到候选全文。',
    'email_not_configured': 'Unpaywall 联系邮箱未配置，已跳过。',
    'license_not_allowed': '未确认可下载许可，仅提供来源链接，请自行查看或上传合法获取的 PDF。',
    'input_changed': '文献已发生变更，请重新查找。',
    'http_error': '来源暂不可用或访问受限，请稍后重试。',
    'lookup_cancelled': '查找已停止。',
    'request_budget_exceeded': '本次请求额度已用完，可分批重试。',
    'download_budget_exceeded': '本次下载大小额度已用完。',
    'download_validation_failed': 'PDF 校验或提取失败，请手动上传。',
}


def lookup_message(code):
    return MESSAGES.get(code, '来源访问、下载或处理失败，可稍后重试或手动上传。') if code else ''
