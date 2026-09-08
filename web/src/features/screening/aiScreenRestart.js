/**
 * Clear the previous AI-screening run and rebuild the left-side list before a
 * replacement task is dispatched. Keeping this sequence explicit prevents the
 * UI from showing the previous run's empty pending list throughout the rerun.
 */
export async function prepareAiScreenRestart({ state, clearResults, loadPending, shouldApply = () => true }) {
  await clearResults()
  if (!shouldApply()) return false

  state.pendingFiles = []
  state.pendingTotal = 0
  state.screenedFiles = []
  state.screenedTotal = 0
  state.aiScreenStats = null
  state.processedCount = 0
  state.screeningProgressValue = 0
  state.totalRefs = 0

  await loadPending()
  return true
}
