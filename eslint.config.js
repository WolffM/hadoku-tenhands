import js from '@eslint/js'
import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import globals from 'globals'
import prettierConfig from 'eslint-config-prettier'

export default [
  {
    ignores: [
      '**/dist/**',
      '**/node_modules/**',
      '**/coverage/**',
      '**/*.test.ts',
      '**/*.test.tsx',
      '**/vite.config.ts'
    ]
  },

  // -------------------------------------------------------------
  // E2E tests and Playwright config (Node.js environment)
  // -------------------------------------------------------------
  {
    files: ['e2e/**/*.ts', 'playwright.config.ts'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        project: './tsconfig.json'
      },
      globals: {
        ...globals.node
      }
    },
    plugins: {
      '@typescript-eslint': tsPlugin
    },
    rules: {
      ...js.configs.recommended.rules,
      ...tsPlugin.configs['recommended'].rules,
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }
      ]
    }
  },

  // -------------------------------------------------------------
  // Base TypeScript + React config
  // -------------------------------------------------------------
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        project: './tsconfig.json'
      },
      globals: {
        // Sanitize keys to fix globals.browser bug (trailing whitespace in "AudioWorkletGlobalScope ")
        ...Object.fromEntries(
          Object.entries(globals.browser).map(([key, value]) => [key.trim(), value])
        )
      }
    },
    plugins: {
      '@typescript-eslint': tsPlugin
    },
    rules: {
      // Pull in all recommended + strict TS rules
      ...js.configs.recommended.rules,
      ...tsPlugin.configs['recommended'].rules,
      ...tsPlugin.configs['recommended-type-checked'].rules,
      ...tsPlugin.configs['stylistic-type-checked'].rules,

      // -----------------------------
      //     SENSIBLE STRICT RULES
      // -----------------------------

      // Prevent sloppy code paths
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/await-thenable': 'error',

      // Avoid silent bugs
      '@typescript-eslint/no-unnecessary-condition': 'off', // Allow defensive null checks
      '@typescript-eslint/no-unnecessary-type-assertion': 'warn',
      '@typescript-eslint/no-confusing-void-expression': ['error', { ignoreArrowShorthand: true }],

      // Real-world strictness
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }
      ],
      '@typescript-eslint/no-explicit-any': ['warn', { fixToUnknown: false }],
      '@typescript-eslint/no-non-null-assertion': 'off', // Allow ! after validation checks

      // Browser correctness
      'no-restricted-globals': ['error', 'event', 'fdescribe'],

      // Safer equality
      eqeqeq: ['error', 'always'],

      // Clean imports
      'no-unused-vars': 'off',
      'no-duplicate-imports': 'error',
      'no-unused-expressions': ['error', { allowShortCircuit: true, allowTernary: true }],

      // Promises must be handled
      'no-void': ['error', { allowAsStatement: true }],

      // Allow console logs when intentional
      'no-console': 'off',

      // Allow intentional || for empty strings and falsy values
      '@typescript-eslint/prefer-nullish-coalescing': 'off',
      '@typescript-eslint/prefer-optional-chain': 'off'
    }
  },

  // -------------------------------------------------------------
  // PRETTIER OVERRIDES (must be last)
  // -------------------------------------------------------------
  prettierConfig
]
