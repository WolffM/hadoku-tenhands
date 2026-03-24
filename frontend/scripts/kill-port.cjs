/**
 * Kill any process listening on the given port.
 * Usage: node scripts/kill-port.cjs [port]
 *
 * Cross-platform: Windows (netstat + process.kill/taskkill) and Unix (lsof + kill).
 * Retries up to 3 times with delays. Uses process.kill() first (works for same-user
 * processes without elevation), falls back to taskkill/kill -9.
 */
const { execSync, execFileSync } = require('child_process')

function validatePort(port) {
  const str = String(port)
  if (!/^\d+$/.test(str)) throw new Error(`Invalid port: ${port}`)
  const num = parseInt(str, 10)
  if (num < 1 || num > 65535) throw new Error(`Invalid port: ${port}. Must be 1-65535.`)
  return String(num)
}

const port = validatePort(process.argv[2] || '5184')

function killWin(p) {
  const killed = new Set()
  try {
    const out = execSync(`netstat -ano`, { encoding: 'utf8' })
    const lines = out.split(/\r?\n/)
    for (const line of lines) {
      if (line.includes(`:${p} `) && /LISTENING/i.test(line)) {
        const parts = line.trim().split(/\s+/)
        const pid = parts[parts.length - 1]
        if (!/^\d+$/.test(pid) || killed.has(pid)) continue
        const numPid = parseInt(pid, 10)
        // Try process.kill first (works for same-user processes without elevation)
        try {
          process.kill(numPid, 'SIGTERM')
          console.log(`[kill-port] Killed PID ${pid} via SIGTERM on port ${p}`)
          killed.add(pid)
          continue
        } catch { /* SIGTERM failed */ }
        try {
          process.kill(numPid, 'SIGKILL')
          console.log(`[kill-port] Killed PID ${pid} via SIGKILL on port ${p}`)
          killed.add(pid)
          continue
        } catch { /* SIGKILL failed */ }
        // Fall back to taskkill (may require elevation)
        try {
          execFileSync('taskkill', ['/PID', pid, '/F'], { stdio: 'ignore' })
          console.log(`[kill-port] Killed PID ${pid} via taskkill on port ${p}`)
          killed.add(pid)
        } catch { /* taskkill failed */ }
      }
    }
  } catch { /* netstat failed */ }
  return killed.size
}

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
    if (process.platform === 'win32') {
      const out = execSync(`netstat -an`, { encoding: 'utf8' })
      return out.split(/\r?\n/).some(l => /LISTENING/i.test(l) && l.includes(`:${p} `))
    }
    const out = execFileSync('lsof', ['-ti', `tcp:${p}`], { encoding: 'utf8' }).trim()
    return !!out
  } catch { return false }
}

const killer = process.platform === 'win32' ? killWin : killUnix

for (let attempt = 0; attempt < 3; attempt++) {
  killer(port)
  if (!portBusy(port)) {
    if (attempt > 0) console.log(`[kill-port] Port ${port} cleared after ${attempt + 1} passes`)
    break
  }
  // Brief delay between attempts (Windows needs time to release port after kill)
  const target = Date.now() + 500
  while (Date.now() < target) { /* busy wait */ }
}

if (portBusy(port)) {
  console.log(`[kill-port] WARNING: Port ${port} still busy after 3 attempts.`)
}
