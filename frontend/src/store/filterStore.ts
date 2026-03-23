/**
 * Filter Store Slice
 *
 * ossExcludedRepos + toggle/set actions.
 */

// ============ Types (re-exported for consumers) ============

export interface FilterSliceState {
  ossExcludedRepos: Set<string>

  toggleOSSRepoFilter: (repo: string) => void
  setOSSRepoFilterAll: () => void
  setOSSRepoFilterNone: (allRepos: string[]) => void
}

// ============ Slice Creator ============

export function createFilterSlice<S extends FilterSliceState>(
  set: (fn: (state: S) => Partial<S>) => void,
  get: () => S
): FilterSliceState {
  return {
    ossExcludedRepos: new Set<string>(),

    toggleOSSRepoFilter: (repo: string) => {
      const next = new Set(get().ossExcludedRepos)
      if (next.has(repo)) {
        next.delete(repo)
      } else {
        next.add(repo)
      }
      set(_s => ({ ossExcludedRepos: next }) as Partial<S>)
    },

    setOSSRepoFilterAll: () => {
      set(_s => ({ ossExcludedRepos: new Set<string>() }) as Partial<S>)
    },

    setOSSRepoFilterNone: (allRepos: string[]) => {
      set(_s => ({ ossExcludedRepos: new Set(allRepos) }) as Partial<S>)
    }
  }
}
