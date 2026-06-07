/**
 * Kill any process listening on the given port.
 * Usage: node scripts/kill-port.cjs [port]
 *
 * Unix (lsof + kill). Retries up to 3 times with delays. Uses kill -9
 * (works for same-user processes without elevation).
 */
const { execFileSync } = require('child_process')

function validatePort(port) {
  const str = String(port)
  if (!/^\d+$/.test(str)) throw new Error(`Invalid port: ${port}`)
  const num = parseInt(str, 10)
  if (num < 1 || num > 65535) throw new Error(`Invalid port: ${port}. Must be 1-65535.`)
  return String(num)
}

const port = validatePort(process.argv[2] || '5184')

function killUnix(p) {
  let count = 0
  try {
    const pids = execFileSync('lsof', ['-ti', `tcp:${p}`], { encoding: 'utf8' })
      .trim().split(/\s+/).filter(Boolean)
    for (const pid of pids) {
      if (!/^\d+$/.test(pid)) continue
      try {
        execFileSync('kill', ['-9', pid])
        console.log(`[kill-port] Killed PID ${pid} on port ${p}`)
        count++
      } catch { /* already dead */ }
    }
  } catch { /* lsof failed */ }
  return count
}

function portBusy(p) {
  try {
    const out = execFileSync('lsof', ['-ti', `tcp:${p}`], { encoding: 'utf8' }).trim()
    return !!out
  } catch { return false }
}

for (let attempt = 0; attempt < 3; attempt++) {
  killUnix(port)
  if (!portBusy(port)) {
    if (attempt > 0) console.log(`[kill-port] Port ${port} cleared after ${attempt + 1} passes`)
    break
  }
  // Brief delay between attempts (time to release port after kill)
  const target = Date.now() + 500
  while (Date.now() < target) { /* busy wait */ }
}

if (portBusy(port)) {
  console.log(`[kill-port] WARNING: Port ${port} still busy after 3 attempts.`)
}
