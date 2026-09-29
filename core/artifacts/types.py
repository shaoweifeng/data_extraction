"""稳定的机器可读产物类型。"""


class ArtifactType:
    SCREENING_SOURCE_REFERENCE_FILE = 'screening_source_reference_file'
    SCREENING_PARSE_REPORT_JSON = 'screening_parse_report_json'
    SCREENING_DEDUP_REPORT_JSON = 'screening_dedup_report_json'
    SCREENING_EXPORT_XLSX = 'screening_export_xlsx'
    SCREENING_EXPORT_RIS = 'screening_export_ris'
    SCREENING_EXPORT_XML = 'screening_export_xml'
    QA_TRAFFIC_LIGHT_PNG = 'qa_traffic_light_png'
    QA_PROPORTION_PNG = 'qa_proportion_png'
