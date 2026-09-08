import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'

export default [
  { ignores: ['dist/**', 'dist_backup_*/**', 'node_modules/**'] },
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    files: ['src/**/*.{js,vue}'],
    languageOptions: {
      globals: {
        alert: 'readonly',
        AbortController: 'readonly',
        Blob: 'readonly',
        clearInterval: 'readonly',
        clearTimeout: 'readonly',
        confirm: 'readonly',
        console: 'readonly',
        CustomEvent: 'readonly',
        document: 'readonly',
        DOMException: 'readonly',
        Event: 'readonly',
        fetch: 'readonly',
        FileReader: 'readonly',
        FormData: 'readonly',
        navigator: 'readonly',
        sessionStorage: 'readonly',
        setInterval: 'readonly',
        setTimeout: 'readonly',
        URL: 'readonly',
        window: 'readonly',
        XMLHttpRequest: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      'no-undef': 'error',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'vue/html-self-closing': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/multi-word-component-names': 'off',
      'vue/singleline-html-element-content-newline': 'off',
    },
  },
]
