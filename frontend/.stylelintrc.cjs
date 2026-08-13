/**
 * Stylelint config — catches `var(--name)` references to custom properties
 * that aren't defined anywhere. @wolffm/themes is the source of truth.
 *
 * The allowed-list rules keep the design-token pass from regressing:
 * font sizes come from the --hdk-text-* scale (calc() on a token is fine
 * for icon-sized text) and z-index from the --th-z-* ladder in theme.css.
 */
module.exports = {
  plugins: ['stylelint-value-no-unknown-custom-properties'],
  rules: {
    'csstools/value-no-unknown-custom-properties': [
      true,
      {
        importFrom: [
          require.resolve('@wolffm/themes/style.css'),
          require.resolve('./src/styles/theme.css'),
        ],
      },
    ],
    'declaration-property-value-allowed-list': {
      'font-size': [/var\(--hdk-text-/, 'inherit', '0'],
      'z-index': [/var\(--th-z-/, 'auto', '-1', '1'],
    },
  },
}
