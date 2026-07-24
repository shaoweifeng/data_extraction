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

if settings.DEBUG:
    from django.views.static import serve as _serve

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    # Vite 构建产物的 assets 目录（前端路由非 /static/ 前缀）
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
