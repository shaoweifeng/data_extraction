"""稳定的机器可读产物类型。"""


class ArtifactType:
    SCREENING_PARSED_REFERENCES_XML = 'screening_parsed_references_xml'
    SCREENING_PARSED_REFERENCE_XML = 'screening_parsed_reference_xml'
    SCREENING_DEDUP_REFERENCE_XML = 'screening_dedup_reference_xml'
    SCREENING_DEDUP_REPORT_JSON = 'screening_dedup_report_json'
    SCREENING_RESULT_JSON = 'screening_result_json'
    SCREENING_EXPORT_XLSX = 'screening_export_xlsx'
    SCREENING_EXPORT_RIS = 'screening_export_ris'
    QA_TRAFFIC_LIGHT_PNG = 'qa_traffic_light_png'
    QA_PROPORTION_PNG = 'qa_proportion_png'
