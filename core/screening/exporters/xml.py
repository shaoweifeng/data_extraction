"""Streaming XML exporter for resolved screening records."""

import xml.etree.ElementTree as ET


class ScreeningXmlExporter:
    FIELD_TAGS = (
        ('ReferenceType', 'ReferenceType'),
        ('Title', 'Title'),
        ('Author', 'Authors'),
        ('Year', 'Year'),
        ('Journal', 'Journal'),
        ('Volume', 'Volume'),
        ('Issue', 'Issue'),
        ('Page', 'Page'),
        ('Date', 'Date'),
        ('Doi', 'Doi'),
        ('PMCID', 'PMCID'),
        ('Abstract', 'Abstract'),
        ('URL', 'URL'),
        ('Address', 'Address'),
    )

    @classmethod
    def write_header(cls, output) -> None:
        output.write('<?xml version="1.0" encoding="UTF-8"?>\n<References>\n')

    @classmethod
    def write_footer(cls, output) -> None:
        output.write('</References>\n')

    @classmethod
    def write_record(cls, output, result: dict, fields: dict, final_decision: str) -> None:
        reference = ET.Element('Reference', {
            'id': str(result.get('reference_id') or ''),
            'decision': final_decision,
            'manual_override': 'yes' if getattr(result.get('_export_manual_review'), 'is_override', False) else 'no',
        })
        for field_name, tag_name in cls.FIELD_TAGS:
            value = fields.get(field_name, '')
            if value in (None, ''):
                continue
            child = ET.SubElement(reference, tag_name)
            child.text = str(value)
        extracted = result.get('extracted_fields')
        if isinstance(extracted, dict) and extracted:
            extracted_node = ET.SubElement(reference, 'ExtractedFields')
            for name, value in extracted.items():
                field = ET.SubElement(extracted_node, 'Field', {'name': str(name)})
                field.text = '' if value is None else str(value)
        output.write(ET.tostring(reference, encoding='unicode', short_empty_elements=True))
        output.write('\n')
