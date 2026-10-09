from django.core.management.base import BaseCommand, CommandError

from core.quality.domain.methods import METHOD_REGISTRY, get_all_methods_meta, get_method_config


class Command(BaseCommand):
    help = '校验并列出质量评价方法配置，不读取文献或调用 AI。'

    def handle(self, *args, **options):
        try:
            metadata = get_all_methods_meta()
            for item in metadata:
                config = get_method_config(item['key'])
                variants = config.get('variants') or {}
                if variants:
                    for variant_key in variants:
                        get_method_config(item['key'], variant_key)
                state = 'AI 可用' if item['ai_supported'] else f"AI 不可用：{item['ai_unavailable_reason']}"
                variant_text = f"，{len(variants)} 个研究设计" if variants else ''
                self.stdout.write(
                    f"{item['key']} v{item['config_version']}：{state}，"
                    f"{item['signal_count']} 条默认信号问题{variant_text}"
                )
        except Exception as exc:
            raise CommandError(f'质量评价方法配置校验失败: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(f'全部 {len(METHOD_REGISTRY)} 种方法配置校验通过。'))
