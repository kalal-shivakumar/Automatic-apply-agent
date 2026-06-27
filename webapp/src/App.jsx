import { useState, useEffect, useRef } from 'react'

const WS_URL = 'ws://localhost:8000/ws'

function App() {
  const [connected, setConnected] = useState(false)
  const [browserLaunched, setBrowserLaunched] = useState(false)
  const [loggedIn, setLoggedIn] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [jobs, setJobs] = useState([])
  const [logs, setLogs] = useState([])
  const [stats, setStats] = useState({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: '' })
  const wsRef = useRef(null)
  const logBoxRef = useRef(null)
  const reconnectRef = useRef(null)

  const addLog = (message) => {
    const time = new Date().toLocaleTimeString('en-US', { hour12: false })
    setLogs((prev) => [...prev.slice(-300), { time, message }])
  }

  const connectWS = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      addLog('Connected to server')
    }

    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
      reconnectRef.current = setTimeout(connectWS, 3000)
    }

    ws.onerror = () => {}

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)
      handleMessage(data)
    }
  }

  const handleMessage = (data) => {
    switch (data.type) {
      case 'init':
        setBrowserLaunched(data.browser_launched)
        setLoggedIn(data.logged_in)
        setIsRunning(data.is_running)
        if (data.jobs?.length) setJobs(data.jobs)
        if (data.stats) setStats(data.stats)
        break

      case 'browser_status':
        setBrowserLaunched(data.launched)
        addLog(data.message)
        break

      case 'login_status':
        setLoggedIn(data.logged_in)
        addLog(data.message)
        break

      case 'agent_started':
        setIsRunning(true)
        setJobs([])
        setStats({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: '' })
        addLog(data.message)
        break

      case 'search_query':
        setStats((s) => ({
          ...s,
          current_query: `${data.keywords} in ${data.location} [${data.query_number}/${data.total_queries}]`,
        }))
        addLog(`🔍 Search [${data.query_number}/${data.total_queries}]: "${data.keywords}" in ${data.location}`)
        break

      case 'log':
        addLog(data.message)
        break

      case 'job_update':
        setJobs((prev) => {
          const idx = prev.findIndex((j) => j.id === data.job.id)
          if (idx >= 0) {
            const updated = [...prev]
            updated[idx] = data.job
            return updated
          }
          return [...prev, data.job]
        })
        if (data.stats) setStats(data.stats)
        if (data.job.status === 'Evaluating...') {
          addLog(`⏳ Evaluating: ${data.job.title} @ ${data.job.company}`)
        } else {
          const icon = data.job.status.includes('Applied') ? '✅' : data.job.status.includes('Error') ? '❌' : '⏭️'
          addLog(
            `${icon} ${data.job.status} — ${data.job.title} @ ${data.job.company} | Score: ${data.job.match_score ?? '?'}% | ${data.job.match_reason}`
          )
        }
        break

      case 'agent_completed':
      case 'agent_stopped':
        setIsRunning(false)
        if (data.stats) setStats(data.stats)
        addLog(`🏁 ${data.message || 'Agent finished'}`)
        break

      case 'error':
        addLog(`❌ ERROR: ${data.message}`)
        break

      default:
        break
    }
  }

  useEffect(() => {
    connectWS()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [])

  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight
    }
  }, [logs])

  const send = (action) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action }))
    }
  }

  const getScoreClass = (score) => {
    if (score == null) return ''
    if (score >= 60) return 'score-good'
    if (score >= 40) return 'score-medium'
    return 'score-low'
  }

  const getRowClass = (status) => {
    if (!status) return ''
    if (status.includes('Applied')) return 'row-applied'
    if (status.includes('Evaluating')) return 'row-evaluating'
    if (status.includes('Error')) return 'row-error'
    return 'row-skipped'
  }

  const getStatusClass = (status) => {
    if (!status) return ''
    if (status.includes('Applied')) return 'badge-applied'
    if (status.includes('Evaluating')) return 'badge-evaluating'
    if (status.includes('Error')) return 'badge-error'
    return 'badge-skipped'
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <h1>🤖 Naukri.com AI Job Agent</h1>
          <span className="subtitle">Automated Job Search & Application</span>
        </div>
        <div className={`conn-badge ${connected ? 'conn-on' : 'conn-off'}`}>
          <span className="conn-dot" />
          {connected ? 'Connected' : 'Disconnected'}
        </div>
      </header>

      <div className="controls">
        <button
          className={`ctrl-btn ${browserLaunched ? 'ctrl-done' : 'ctrl-primary'}`}
          onClick={() => send('launch_browser')}
          disabled={browserLaunched || isRunning}
        >
          <span className="ctrl-step">1</span>
          <div className="ctrl-content">
            <span className="ctrl-title">{browserLaunched ? 'Browser Launched ✓' : 'Launch Browser'}</span>
            <span className="ctrl-desc">Opens Chromium for Naukri login</span>
          </div>
        </button>

        <span className="ctrl-arrow">→</span>

        <button
          className={`ctrl-btn ${loggedIn ? 'ctrl-done' : 'ctrl-primary'}`}
          onClick={() => send('verify_login')}
          disabled={!browserLaunched || loggedIn || isRunning}
        >
          <span className="ctrl-step">2</span>
          <div className="ctrl-content">
            <span className="ctrl-title">{loggedIn ? 'Logged In ✓' : 'Verify Login'}</span>
            <span className="ctrl-desc">Confirm Naukri login status</span>
          </div>
        </button>

        <span className="ctrl-arrow">→</span>

        <button
          className={`ctrl-btn ${isRunning ? 'ctrl-danger' : 'ctrl-success'}`}
          onClick={() => send(isRunning ? 'stop' : 'start')}
          disabled={!loggedIn}
        >
          <span className="ctrl-step">3</span>
          <div className="ctrl-content">
            <span className="ctrl-title">{isRunning ? '■ Stop Agent' : '▶ Start Applying'}</span>
            <span className="ctrl-desc">{isRunning ? 'Stop the automation' : 'Begin job search & apply'}</span>
          </div>
        </button>
      </div>

      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-value">{stats.evaluated}</div>
          <div className="stat-label">Evaluated</div>
        </div>
        <div className="stat-card stat-green">
          <div className="stat-value">{stats.applied}</div>
          <div className="stat-label">Applied</div>
        </div>
        <div className="stat-card stat-red">
          <div className="stat-value">{stats.skipped}</div>
          <div className="stat-label">Skipped</div>
        </div>
        <div className="stat-card stat-orange">
          <div className="stat-value">{stats.already_applied}</div>
          <div className="stat-label">Already Applied</div>
        </div>
        {stats.current_query && (
          <div className="stat-card stat-blue stat-wide">
            <div className="stat-value-sm">🔍</div>
            <div className="stat-label">{stats.current_query}</div>
          </div>
        )}
      </div>

      <div className="content-area">
        <section className="section">
          <h2>
            Job Results
            {jobs.length > 0 && <span className="count">({jobs.length})</span>}
        </h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Company</th>
                <th>Job Title</th>
                <th>Location</th>
                <th>Salary</th>
                <th>Experience</th>
                <th>Match</th>
                <th>Status</th>
                <th>AI Analysis</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id} className={getRowClass(job.status)}>
                  <td className="col-num">{job.id}</td>
                  <td className="col-company">{job.company}</td>
                  <td className="col-title">
                    {job.url ? (
                      <a href={job.url} target="_blank" rel="noopener noreferrer" className="job-link">{job.title}</a>
                    ) : job.title}
                  </td>
                  <td>{job.location}</td>
                  <td>{job.salary}</td>
                  <td>{job.experience}</td>
                  <td>
                    <span className={`score-badge ${getScoreClass(job.match_score)}`}>
                      {job.match_score != null ? `${job.match_score}%` : '...'}
                    </span>
                  </td>
                  <td>
                    <span className={`status-badge ${getStatusClass(job.status)}`}>{job.status}</span>
                  </td>
                  <td className="col-reason">{job.match_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {jobs.length === 0 && (
            <div className="empty">No jobs evaluated yet. Launch browser, login, and start the agent.</div>
          )}
        </div>
      </section>

      <section className="section">
        <h2>
          Activity Log
          {logs.length > 0 && <span className="count">({logs.length})</span>}
        </h2>
        <div className="log-box" ref={logBoxRef}>
          {logs.map((log, i) => (
            <div key={i} className="log-line">
              <span className="log-time">[{log.time}]</span>
              <span className="log-msg">{log.message}</span>
            </div>
          ))}
        </div>
      </section>
      </div>
    </div>
  )
}

export default App
