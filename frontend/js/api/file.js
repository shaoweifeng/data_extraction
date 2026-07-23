/**
 * frontend/js/api/file.js
 *
 * 文件相关 API 调用层（DataFile）。
 * 通过 window.AppFileApi 暴露，供 index.html 的 Vue setup() 使用。
 *
 * 使用示例（setup 内）：
 *   const fileApi = AppFileApi.create(http, state, API_BASE);
 *   await fileApi.loadScreen1Files();
 *   await fileApi.deleteFile(fileId);
 */

(function (global) {
    'use strict';

    /** 支持上传/展示的参考文献文件扩展名列表。 */
    const SUPPORTED_EXTENSIONS = [
        '.ris', '.bib', '.nbib', '.xml', '.ciw', '.enw', '.txt', '.doc', '.docx'
    ];

    /**
     * 判断文件名是否为受支持的参考文献格式。
     * @param {string} filename
     * @returns {boolean}
     */
    function isSupportedRefFile(filename) {
        return SUPPORTED_EXTENSIONS.some(ext => filename.endsWith(ext));
    }

    /**
     * 创建文件 API 客户端。
     *
     * @param {object} http       AppHttp.create() 返回的客户端
     * @param {object} state      Vue setup 中的 reactive 引用
     * @param {string} apiBase    API 前缀
     * @returns {object}
     */
    function create(http, state, apiBase) {
        const { extractListData } = global.AppUtils;

        /**
         * 加载 SCREEN_1 阶段的输入文件列表（参考文献），并加载纳排标准。
         * 对应原 loadScreen1Files。
         */
        async function loadScreen1Files() {
            try {
                const res = await http.request(
                    `${apiBase}/files/?project=${state.currentProject.value.id}&data_category=input`
                );
                if (res.ok) {
                    const data = await res.json();
                    const files = extractListData(data);
                    state.referenceFiles.value = files.filter(f => isSupportedRefFile(f.filename));
                }
            } catch (err) {
                console.error('加载文件失败', err);
            }
        }

        /**
         * 删除指定文件，成功后刷新文件列表。
         * @param {number|string} fileId
         */
        async function deleteFile(fileId) {
            if (!confirm('确定要删除该文件吗？')) return;
            try {
                const res = await http.request(`${apiBase}/files/${fileId}/`, {
                    method: 'DELETE',
                });
                if (res.ok || res.status === 204) {
                    await loadScreen1Files();
                } else {
                    const data = await res.json().catch(() => ({}));
                    alert(data.error || '删除失败');
                }
            } catch (err) {
                alert(`删除文件出错: ${err.message}`);
            }
        }

        /**
         * 加载指定步骤的导出文件列表，更新 exportFiles。
         * @param {number} projectId
         * @param {number} stepId
         */
        async function loadExportFiles(projectId, stepId) {
            if (!stepId) return;
            try {
                const res = await http.request(
                    `${apiBase}/files/?project=${projectId}&step=${stepId}&data_category=output&limit=100`
                );
                if (res.ok) {
                    const data = await res.json();
                    state.exportFiles.value = extractListData(data);
                }
            } catch (e) { /* ignore */ }
        }

        return { loadScreen1Files, deleteFile, loadExportFiles, isSupportedRefFile };
    }

    // ── 导出 ──────────────────────────────────────────────────────────────

    global.AppFileApi = { create, isSupportedRefFile, SUPPORTED_EXTENSIONS };

})(window);
