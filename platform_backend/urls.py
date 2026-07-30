import os
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView


# SPA fallback：所有非 /api/ 、非 /admin/ 、非 /media/ 、非 /static/ 、非 /assets/ 的路由
# 都返回 Vue 的 index.html，由前端路由处理
class SPAView(TemplateView):
    """Serve the Vue SPA index.html for all non-API routes."""
    template_name = 'index.html'


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('core.urls')),
    # SPA fallback — 必须放在最后
    re_path(r'^(?!api/|admin/|media/|static/|assets/).*$', SPAView.as_view()),
]

from django.views.static import serve as _serve

# media（任务日志、用户上传等动态文件）：无论 DEBUG 与否都需可访问。
# 前端会通过 /media/ 读取任务日志等，生产环境(DEBUG=False)下同样要托管。
# 注：media 是运行时动态生成的文件，不适合走 whitenoise 静态清单，用 Django serve 即可（个人项目足够）。
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', _serve, {'document_root': settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # 开发环境下由 Django 直接 serve Vite 产物；
    # 生产环境(DEBUG=False)下这些资源由 WhiteNoise(WHITENOISE_ROOT=web/dist) 接管。
    _vite_assets = os.path.join(settings.BASE_DIR, 'web', 'dist', 'assets')
    if os.path.isdir(_vite_assets):
        urlpatterns += [
            re_path(r'^assets/(?P<path>.*)$', _serve, {'document_root': _vite_assets}),
        ]

    # Vite 构建产物根目录（favicon.svg 等）
    _vite_dist = os.path.join(settings.BASE_DIR, 'web', 'dist')
    if os.path.isdir(_vite_dist):
        urlpatterns += [
            re_path(r'^(?P<path>favicon\.svg|icons\.svg)$', _serve, {'document_root': _vite_dist}),
        ]
