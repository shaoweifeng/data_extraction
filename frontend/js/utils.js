/**
 * frontend/js/utils.js
 *
 * 纯工具函数模块（无副作用，无 Vue reactive 依赖）。
 * 通过 window.AppUtils 暴露，供 index.html 的 Vue setup() 使用。
 *
 * 包含：
 *  - getCSRFToken      CSRF token 读取
 *  - extractListData   统一解析 DRF 分页/非分页响应
 *  - fetchWithTimeout  带超时的 fetch 封装
 *  - formatDuration    秒数 → 可读时长
 *  - getTaskTypeName   task_type/step_key → 中文名
 *  - getTaskStatusClass 任务状态 → Tailwind CSS 类
 *  - getTaskStatusName  任务状态 → 中文名
 *  - getLogTypeClass   操作日志类型 → Tailwind 颜色类
 *  - getLogDetail      操作日志 → 详情文本
 *  - getShortError     错误信息截断（50 字符）
 *  - exportFileLabel   导出文件名 → 版本标签
 */

(function (global) {
    'use strict';

    // ── CSRF ─────────────────────────────────────────────────────────────

    /**
     * 从 cookie 中读取 Django CSRF token。
     * @returns {string|undefined}
     */
    function getCSRFToken() {
        return document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];
    }

    // ── HTTP 基础 ─────────────────────────────────────────────────────────

    /**
     * 解析 DRF 响应：兼容分页 { results: [] } 和直接数组两种格式。
     * @param {any} payload
     * @returns {Array}
     */
    function extractListData(payload) {
        if (Array.isArray(payload)) return payload;
        if (Array.isArray(payload?.results)) return payload.results;
        return [];
    }

    /**
     * 带超时的 fetch 封装。
     * @param {string} url
     * @param {RequestInit} options
     * @param {number} timeoutMs  超时毫秒数，默认 15000
     * @returns {Promise<Response>}
     */
    async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        try {
            return await fetch(url, { ...options, signal: controller.signal });
        } finally {
            clearTimeout(timeoutId);
        }
    }

    // ── 格式化 ────────────────────────────────────────────────────────────

    /**
     * 秒数格式化为 "X时Y分Z秒"。
     * @param {number} seconds
     * @returns {string}
     */
    function formatDuration(seconds) {
        if (!seconds || seconds <= 0) return '0秒';
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        const parts = [];
        if (hours > 0) parts.push(`${hours}时`);
        if (minutes > 0) parts.push(`${minutes}分`);
        if (secs > 0) parts.push(`${secs}秒`);
        return parts.join('') || '0秒';
    }

    /**
     * 任务类型/步骤 key → 中文显示名称。
     * @param {string} taskType
     * @returns {string}
     */
    function getTaskTypeName(taskType) {
        const names = {
            // 前端 task_type（POST 时传入）
            'reference_parsing': '文献解析',
            'deduplication': '文献去重',
            'ai_screening': 'AI初筛',
            'result_aggregation': '结果归纳',
            // 后端 step_key（实际存入 DB 的值）
            'parse': '文献解析',
            'dedup': '文献去重',
            'ai_screen': 'AI初筛',
            'export': '结果归纳',
            'criteria': '纳排标准',
            'SCREEN_1': '初筛阶段',
            'SEARCH': '文献检索',
        };
        return names[taskType] || taskType;
    }

    /**
     * 任务状态 → Tailwind CSS 背景+文字颜色类。
     * @param {string} status
     * @returns {string}
     */
    function getTaskStatusClass(status) {
        const classes = {
            'completed': 'bg-green-100 text-green-800',
            'running':   'bg-blue-100 text-blue-800',
            'pending':   'bg-gray-100 text-gray-800',
            'failed':    'bg-red-100 text-red-800',
            'stopped':   'bg-yellow-100 text-yellow-800',
        };
        return classes[status] || 'bg-gray-100 text-gray-800';
    }

    /**
     * 任务状态 → 中文显示名称。
     * @param {string} status
     * @returns {string}
     */
    function getTaskStatusName(status) {
        const names = {
            'completed': '已完成',
            'running':   '执行中',
            'pending':   '等待中',
            'failed':    '失败',
            'stopped':   '已停止',
        };
        return names[status] || status;
    }

    /**
     * 操作日志类型 → Tailwind 背景色类（用于圆点/标签）。
     * @param {string} opType
     * @returns {string}
     */
    function getLogTypeClass(opType) {
        const map = {
            'file_add':               'bg-blue-500',
            'file_delete':            'bg-red-500',
            'criteria_add':           'bg-green-500',
            'criteria_delete':        'bg-orange-500',
            'task_start_parse':       'bg-indigo-500',
            'task_start_dedup':       'bg-purple-500',
            'task_start_ai_screen':   'bg-violet-500',
            'task_start_export':      'bg-teal-500',
            'task_stop':              'bg-yellow-500',
            'task_resume':            'bg-green-500',
            'task_abandon':           'bg-gray-500',
            'prompt_set':             'bg-purple-500',
            'prompt_reset':           'bg-gray-400',
            'model_select':           'bg-blue-400',
            'field_extraction_add':   'bg-orange-400',
            'field_extraction_delete':'bg-red-400',
        };
        return map[opType] || 'bg-gray-400';
    }

    /**
     * 操作日志对象 → 详情文本。
     * @param {Object} log
     * @returns {string}
     */
    function getLogDetail(log) {
        const d = log.operation_detail || {};
        if (log.operation_type === 'prompt_set') {
            return d.use_custom
                ? `自定义 Prompt（${d.prompt_length || 0} 字符）`
                : '切换为默认 Prompt';
        }
        if (log.operation_type === 'prompt_reset') return '已重置为默认 Prompt';
        if (log.operation_type === 'model_select')
            return `切换为 ${d.model_name || d.model_id}`;
        if (log.operation_type === 'field_extraction_add')
            return `添加字段: ${d.field_name || ''}`;
        if (log.operation_type === 'field_extraction_delete')
            return `删除字段: ${d.field_name || ''}`;
        if (d.filename) return d.filename;
        if (d.criteria) return d.criteria;
        if (d.task_type) return d.task_type;
        return '';
    }

    /**
     * 截断错误信息（超过 50 字符时加省略号）。
     * @param {string} errorMsg
     * @returns {string}
     */
    function getShortError(errorMsg) {
        if (!errorMsg) return '';
        return errorMsg.length > 50
            ? errorMsg.substring(0, 50) + '...'
            : errorMsg;
    }

    /**
     * 导出文件对象 → 版本标签字符串。
     * 文件名格式：screening_results_{type}_{model}_{YYYYMMDD}_{HHMMSS}.ext
     * @param {Object} f  DataFile 对象（含 filename, created_at）
     * @returns {string}
     */
    function exportFileLabel(f) {
        const name = f.filename || '';
        const m = name.match(
            /screening_results_(?:all|included|excluded)_(.+?)_(\d{8})_(\d{6})\./
        );
        if (m) {
            const model = m[1];
            const d = m[2]; // 20260512
            const t = m[3]; // 195500
            const dateStr = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)} ${t.slice(0, 2)}:${t.slice(2, 4)}`;
            return `${model}  ${dateStr}`;
        }
        // fallback：用创建时间
        return f.created_at?.slice(0, 16) || name;
    }

    // ── 导出 ──────────────────────────────────────────────────────────────

    global.AppUtils = {
        getCSRFToken,
        extractListData,
        fetchWithTimeout,
        formatDuration,
        getTaskTypeName,
        getTaskStatusClass,
        getTaskStatusName,
        getLogTypeClass,
        getLogDetail,
        getShortError,
        exportFileLabel,
    };

})(window);
