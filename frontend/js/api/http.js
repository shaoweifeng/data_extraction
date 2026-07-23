/**
 * frontend/js/api/http.js
 *
 * HTTP 请求封装层。
 * 通过 window.AppHttp 暴露，供 index.html 的 Vue setup() 使用。
 *
 * 设计原则：
 *  - 本文件不依赖任何 Vue reactive 对象
 *  - 鉴权失败（401/403）时调用调用方传入的 onUnauthorized 回调，
 *    由 Vue 层负责更新 showLoginModal.value = true
 *  - 依赖 AppUtils.getCSRFToken / AppUtils.fetchWithTimeout（需先引入 utils.js）
 *
 * 使用示例（setup 内）：
 *   const http = AppHttp.create({
 *       apiBase: API_BASE,
 *       timeoutMs: REQUEST_TIMEOUT_MS,
 *       onUnauthorized: () => { showLoginModal.value = true; },
 *   });
 *   const res = await http.request('/projects/');
 *   const res = await http.requestNoTimeout('/tasks/1/start/', { method: 'POST' });
 */

(function (global) {
    'use strict';

    /**
     * 创建一个绑定了配置的 http 客户端对象。
     *
     * @param {object} opts
     * @param {string}   opts.apiBase        API 前缀，如 '/api'
     * @param {number}  [opts.timeoutMs]     请求超时毫秒，默认 15000
     * @param {Function}[opts.onUnauthorized] 401/403 时的回调
     * @returns {{ request: Function, requestNoTimeout: Function }}
     */
    function create(opts = {}) {
        const {
            apiBase = '/api',
            timeoutMs = 15000,
            onUnauthorized = () => {},
        } = opts;

        const { getCSRFToken, fetchWithTimeout } = global.AppUtils;

        function _defaultHeaders() {
            return {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken() || '',
            };
        }

        /**
         * 带超时的 API 请求（适合普通读写操作）。
         * @param {string} url       完整 URL 或相对路径（若以 / 开头则拼 apiBase）
         * @param {RequestInit} [options]
         * @returns {Promise<Response>}
         */
        async function request(url, options = {}) {
            const fullUrl = url.startsWith('http') ? url : url;
            const merged = {
                headers: _defaultHeaders(),
                credentials: 'include',
                ...options,
                headers: { ..._defaultHeaders(), ...(options.headers || {}) },
            };
            const response = await fetchWithTimeout(fullUrl, merged, timeoutMs);
            if (!response.ok && (response.status === 401 || response.status === 403)) {
                onUnauthorized();
                throw new Error('未登录');
            }
            return response;
        }

        /**
         * 不带超时的 API 请求（适合任务启动/停止/续传等耗时操作）。
         * @param {string} url
         * @param {RequestInit} [options]
         * @returns {Promise<Response>}
         */
        async function requestNoTimeout(url, options = {}) {
            const merged = {
                headers: _defaultHeaders(),
                credentials: 'include',
                ...options,
                headers: { ..._defaultHeaders(), ...(options.headers || {}) },
            };
            const response = await fetch(url, merged);
            if (!response.ok && (response.status === 401 || response.status === 403)) {
                onUnauthorized();
                throw new Error('未登录');
            }
            return response;
        }

        return { request, requestNoTimeout };
    }

    // ── 导出 ──────────────────────────────────────────────────────────────

    global.AppHttp = { create };

})(window);
