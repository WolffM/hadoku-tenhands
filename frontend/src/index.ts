// Re-export public API from entry point
// This file ensures dist/index.d.ts is generated to match package.json exports
export { mount, unmount } from './entry'
export type { VibeDispatchProps } from './entry'
