const { useEffect, useMemo, useRef, useState } = React;

const WS_URL = "ws://localhost:8000/ws";

const defaultProfile = {
  full_name: "",
  skills: [],
  job_titles: [],
  salary_min_lpa: "",
  salary_max_lpa: "",
  overall_experience_years: "",
  key_search_keywords: [],
  preferred_location: "Hyderabad",
  ready_to_relocate: true,
  search_locations: [
    "Hyderabad",
    "Bangalore",
    "Chennai",
    "Pune",
    "Mumbai",
    "Noida",
    "Gurugram",
    "Delhi",
    "Kolkata",
    "Ahmedabad",
  ],
  resume_file_name: "",
};

function splitCsv(value) {
  return String(value || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

function arrayBufferToBase64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function App() {
  const [activeTab, setActiveTab] = useState("home");
  const [connected, setConnected] = useState(false);
  const [browserLaunched, setBrowserLaunched] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  const [jobs, setJobs] = useState([]);
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: "" });

  const [resumeFile, setResumeFile] = useState(null);
  const [uploadPayload, setUploadPayload] = useState({ resumeText: "", fileBase64: "", mimeType: "" });
  const [resumeText, setResumeText] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [profile, setProfile] = useState(defaultProfile);
  const [resumeSummary, setResumeSummary] = useState([]);
  const [profileSaved, setProfileSaved] = useState(false);
  const [homeMessage, setHomeMessage] = useState("");
  const [homeError, setHomeError] = useState("");

  const wsRef = useRef(null);
  const reconnectRef = useRef(null);
  const logBoxRef = useRef(null);

  const skillsText = useMemo(() => (profile.skills || []).join(", "), [profile.skills]);
  const jobTitlesText = useMemo(() => (profile.job_titles || []).join(", "), [profile.job_titles]);
  const keywordText = useMemo(() => (profile.key_search_keywords || []).join(", "), [profile.key_search_keywords]);
  const locationText = useMemo(() => (profile.search_locations || []).join(", "), [profile.search_locations]);

  const addLog = (message) => {
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });
    setLogs((prev) => [...prev.slice(-350), { time, message }]);
  };

  const send = (payload) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
      return true;
    }
    return false;
  };

  const handleMessage = (data) => {
    switch (data.type) {
      case "init":
        setBrowserLaunched(Boolean(data.browser_launched));
        setLoggedIn(Boolean(data.logged_in));
        setIsRunning(Boolean(data.is_running));
        if (Array.isArray(data.jobs)) setJobs(data.jobs);
        if (data.stats) setStats(data.stats);
        if (data.saved_profile) {
          setProfile({ ...defaultProfile, ...data.saved_profile });
          const hasProfile =
            Array.isArray(data.saved_profile.skills) && data.saved_profile.skills.length > 0;
          setProfileSaved(hasProfile);
        }
        break;

      case "resume_analyzed":
        setIsAnalyzing(false);
        if (data.profile) {
          setProfile({ ...defaultProfile, ...data.profile });
          const paragraphs = Array.isArray(data.summary_paragraphs) ? data.summary_paragraphs : [];
          setResumeSummary(paragraphs.slice(0, 2));
          setHomeMessage(data.message || "Resume analyzed successfully.");
          setHomeError("");
          setProfileSaved(false);
          addLog("Resume analyzed and profile fields generated.");
        }
        break;

      case "profile_saved":
        if (data.profile) setProfile({ ...defaultProfile, ...data.profile });
        setProfileSaved(true);
        setHomeMessage(data.message || "Profile saved.");
        setHomeError("");
        addLog("Profile saved for Automatic Job Apply.");
        break;

      case "browser_status":
        setBrowserLaunched(Boolean(data.launched));
        addLog(data.message || "Browser status updated.");
        break;

      case "login_status":
        setLoggedIn(Boolean(data.logged_in));
        addLog(data.message || "Login status updated.");
        break;

      case "agent_started":
        setIsRunning(true);
        setJobs([]);
        setStats({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: "" });
        addLog(data.message || "Agent started.");
        break;

      case "search_query":
        setStats((s) => ({
          ...s,
          current_query: `${data.keywords} in ${data.location} [${data.query_number}/${data.total_queries}]`,
        }));
        addLog(`Search ${data.query_number}/${data.total_queries}: ${data.keywords} in ${data.location}`);
        break;

      case "job_update":
        setJobs((prev) => {
          const index = prev.findIndex((j) => j.id === data.job.id);
          if (index >= 0) {
            const next = [...prev];
            next[index] = data.job;
            return next;
          }
          return [...prev, data.job];
        });
        if (data.stats) setStats(data.stats);
        break;

      case "agent_completed":
      case "agent_stopped":
        setIsRunning(false);
        if (data.stats) setStats(data.stats);
        addLog(data.message || "Agent stopped.");
        break;

      case "log":
        addLog(data.message || "");
        break;

      case "error":
        addLog(`ERROR: ${data.message || "Unknown error"}`);
        if (isAnalyzing) setIsAnalyzing(false);
        setHomeError(data.message || "Resume analysis failed.");
        break;

      default:
        break;
    }
  };

  const connectWS = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      addLog("Connected to server.");
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      reconnectRef.current = setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {};
    ws.onmessage = (e) => {
      try {
        handleMessage(JSON.parse(e.data));
      } catch (_err) {
        addLog("Received malformed server payload.");
      }
    };
  };

  useEffect(() => {
    connectWS();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  useEffect(() => {
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logs]);

  const onUploadResume = async (event) => {
    setHomeError("");
    setHomeMessage("");
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    setResumeFile(file);
    setProfileSaved(false);

    try {
      const mimeType = file.type || "";
      const ext = (file.name.split(".").pop() || "").toLowerCase();
      const isPdf = mimeType === "application/pdf" || ext === "pdf";

      if (isPdf) {
        const buffer = await file.arrayBuffer();
        const fileBase64 = arrayBufferToBase64(buffer);
        const payload = { resumeText: "", fileBase64, mimeType };
        setUploadPayload(payload);
        setResumeText("");
        setHomeMessage("PDF uploaded. Analyzing with AI...");
        onAnalyzeResume(file, payload);
      } else {
        const text = await file.text();
        setResumeText(text || "");
        const payload = { resumeText: text || "", fileBase64: "", mimeType };
        setUploadPayload(payload);
        if (!text || !text.trim()) {
          setHomeError("Unable to read text from this file. Please upload a text-based resume.");
        } else {
          setHomeMessage("Resume uploaded. Analyzing with AI...");
          onAnalyzeResume(file, payload);
        }
      }
    } catch (_err) {
      setResumeText("");
      setUploadPayload({ resumeText: "", fileBase64: "", mimeType: "" });
      setHomeError("Failed to read the uploaded file. Please try another resume file.");
    }
  };

  const onAnalyzeResume = (fileArg, payloadArg) => {
    setHomeError("");
    setHomeMessage("");
    const selectedFile = fileArg || resumeFile;
    const selectedPayload = payloadArg || uploadPayload;
    const selectedText = selectedPayload.resumeText || resumeText;
    const selectedFileBase64 = selectedPayload.fileBase64 || "";
    const selectedMimeType = selectedPayload.mimeType || "";

    if (!selectedFile) {
      setHomeError("Please upload your resume first.");
      return;
    }
    if ((!selectedText || !selectedText.trim()) && !selectedFileBase64) {
      setHomeError("Resume text is empty. Please upload a text-based resume.");
      return;
    }
    setResumeSummary([]);
    const sent = send({
      action: "analyze_resume",
      file_name: selectedFile.name,
      resume_text: selectedText,
      file_base64: selectedFileBase64,
      mime_type: selectedMimeType,
    });
    if (!sent) {
      setHomeError("Not connected to server.");
      return;
    }
    setIsAnalyzing(true);
    setHomeMessage("Analyzing resume with AI...");
  };

  const onSaveProfile = () => {
    setHomeError("");
    setHomeMessage("");

    const normalized = {
      ...profile,
      skills: splitCsv(skillsText),
      job_titles: splitCsv(jobTitlesText).slice(0, 20),
      key_search_keywords: splitCsv(keywordText).slice(0, 10),
      search_locations: splitCsv(locationText).slice(0, 15),
      preferred_location: String(profile.preferred_location || "").trim() || "Hyderabad",
      ready_to_relocate: Boolean(profile.ready_to_relocate),
    };

    if (!normalized.skills.length || normalized.skills.length < 10) {
      setHomeError("Please provide at least 10 skills.");
      return;
    }
    if (!normalized.job_titles.length || normalized.job_titles.length < 10) {
      setHomeError("Please provide at least 10 job titles to search.");
      return;
    }
    if (!normalized.key_search_keywords.length || normalized.key_search_keywords.length < 5) {
      setHomeError("Please provide at least 5 search keywords.");
      return;
    }

    const sent = send({ action: "save_profile", profile: normalized });
    if (!sent) {
      setHomeError("Not connected to server.");
      return;
    }
  };

  const updateProfile = (key, value) => {
    setProfile((prev) => ({ ...prev, [key]: value }));
    setProfileSaved(false);
  };

  return (
    <div className="app-shell">
      <header className="hero">
        <h1>Naukri AI Job Agent</h1>
        <p>Two-step flow: analyze your resume on HOME, then run Automatic Job Apply with saved profile data.</p>
        <div className="conn">
          <span className={`conn-dot ${connected ? "on" : ""}`} />
          {connected ? "Connected" : "Disconnected"}
        </div>
        <div className="tabs">
          <button className={`tab-btn ${activeTab === "home" ? "active" : ""}`} onClick={() => setActiveTab("home")}>HOME</button>
          <button className={`tab-btn ${activeTab === "apply" ? "active" : ""}`} onClick={() => setActiveTab("apply")}>Automatic Job Apply</button>
        </div>
      </header>

      {activeTab === "home" && (
        <section className="panel">
          <h2 className="card-title">HOME</h2>
          <div className="field">
            <label>Upload your resume here</label>
            <input type="file" accept=".txt,.md,.rtf,.pdf,.doc,.docx" onChange={onUploadResume} />
            <div className="helper">After upload, AI analysis starts automatically and fields below get updated.</div>
          </div>

          <div className="row" style={{ marginTop: "10px" }}>
            <button className="btn btn-primary" onClick={onAnalyzeResume} disabled={!resumeFile || isAnalyzing}>
              {isAnalyzing ? "Analyzing..." : "Analyze My Resume"}
            </button>
            <button className="btn btn-light" onClick={onSaveProfile}>Save Profile for Automatic Job Apply</button>
          </div>

          {homeMessage && <div className="alert alert-ok" style={{ marginTop: "12px" }}>{homeMessage}</div>}
          {homeError && <div className="alert alert-danger" style={{ marginTop: "12px" }}>{homeError}</div>}
          {resumeSummary.length > 0 && (
            <div className="summary-box" style={{ marginTop: "12px" }}>
              <h3>AI Resume Summary</h3>
              {resumeSummary.map((paragraph, idx) => (
                <p key={`summary-${idx}`}>{paragraph}</p>
              ))}
            </div>
          )}
          {!profileSaved && !homeError && (
            <div className="status-line">All fields are editable. Save after review so tab 2 can use your data.</div>
          )}

          <div className="grid-2" style={{ marginTop: "14px" }}>
            <div className="field">
              <label>1. Full Name</label>
              <input value={profile.full_name || ""} onChange={(e) => updateProfile("full_name", e.target.value)} />
            </div>
            <div className="field">
              <label>4. What is your overall experience (years)</label>
              <input value={profile.overall_experience_years || ""} onChange={(e) => updateProfile("overall_experience_years", e.target.value)} />
            </div>
          </div>

          <div className="grid-2" style={{ marginTop: "12px" }}>
            <div className="field">
              <label>3. Salary expectations min LPA</label>
              <input value={profile.salary_min_lpa || ""} onChange={(e) => updateProfile("salary_min_lpa", e.target.value)} />
            </div>
            <div className="field">
              <label>3. Salary expectations max LPA</label>
              <input value={profile.salary_max_lpa || ""} onChange={(e) => updateProfile("salary_max_lpa", e.target.value)} />
            </div>
          </div>

          <div className="grid-2" style={{ marginTop: "12px" }}>
            <div className="field">
              <label>Preferred location</label>
              <input value={profile.preferred_location || ""} onChange={(e) => updateProfile("preferred_location", e.target.value)} />
            </div>
            <div className="field">
              <label>Ready to relocate</label>
              <select
                value={profile.ready_to_relocate ? "yes" : "no"}
                onChange={(e) => updateProfile("ready_to_relocate", e.target.value === "yes")}
              >
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </select>
            </div>
          </div>

          <div className="field" style={{ marginTop: "12px" }}>
            <label>Search cities (major cities in priority order)</label>
            <textarea
              value={locationText}
              onChange={(e) => updateProfile("search_locations", splitCsv(e.target.value))}
              placeholder="Hyderabad, Bangalore, Chennai, Pune, Mumbai, Noida..."
            />
            <div className="helper">Job search will start from Hyderabad, Bangalore, Chennai, then remaining cities listed here.</div>
          </div>

          <div className="field" style={{ marginTop: "12px" }}>
            <label>2. Skills found from resume (add more if needed, at least 10)</label>
            <textarea
              value={skillsText}
              onChange={(e) => updateProfile("skills", splitCsv(e.target.value))}
              placeholder="Azure, Terraform, PowerShell, Python, DevOps, Kubernetes..."
            />
            <div className="helper">Comma-separated values. Minimum 10 skills.</div>
          </div>

          <div className="field" style={{ marginTop: "12px" }}>
            <label>Job titles AI will search (at least 10)</label>
            <textarea
              value={jobTitlesText}
              onChange={(e) => updateProfile("job_titles", splitCsv(e.target.value))}
              placeholder="DevOps Engineer, Senior DevOps Engineer, Azure DevOps Engineer..."
            />
            <div className="helper">These titles drive job search queries directly. Minimum 10 titles.</div>
          </div>

          <div className="field" style={{ marginTop: "12px" }}>
            <label>6. Search keywords from resume (at least 5)</label>
            <textarea
              value={keywordText}
              onChange={(e) => updateProfile("key_search_keywords", splitCsv(e.target.value))}
              placeholder="Azure DevOps Engineer, Terraform Engineer, Platform Engineer..."
            />
            <div className="helper">These keywords will drive automatic job search in tab 2.</div>
          </div>

          {Array.isArray(profile.skills) && profile.skills.length > 0 && (
            <div className="chips">
              {profile.skills.map((skill, idx) => (
                <span className="chip" key={`${skill}-${idx}`}>{skill}</span>
              ))}
            </div>
          )}
        </section>
      )}

      {activeTab === "apply" && (
        <section className="panel">
          <h2 className="card-title">Automatic Job Apply</h2>

          {!profileSaved ? (
            <div className="alert alert-warn">
              Please complete HOME tab and click Save Profile first. This tab uses that saved data before applying jobs.
            </div>
          ) : (
            <div className="alert alert-ok">
              Profile loaded: {profile.full_name || "Candidate"} | Experience: {profile.overall_experience_years || "N/A"} years | Salary: {profile.salary_min_lpa || "?"}-{profile.salary_max_lpa || "?"} LPA
            </div>
          )}

          <div className="control-strip">
            <div className="ctrl">
              <h4>1. Launch Browser</h4>
              <p>Open Naukri login browser session.</p>
              <div className="row" style={{ marginTop: "10px" }}>
                <button className="btn btn-light" onClick={() => send({ action: "launch_browser" })} disabled={browserLaunched || isRunning}>
                  {browserLaunched ? "Launched" : "Launch"}
                </button>
              </div>
            </div>
            <div className="ctrl">
              <h4>2. Verify Login</h4>
              <p>Confirm your manual login in browser.</p>
              <div className="row" style={{ marginTop: "10px" }}>
                <button className="btn btn-light" onClick={() => send({ action: "verify_login" })} disabled={!browserLaunched || loggedIn || isRunning}>
                  {loggedIn ? "Verified" : "Verify"}
                </button>
              </div>
            </div>
            <div className="ctrl">
              <h4>3. Start / Stop Apply</h4>
              <p>Runs search using saved keywords and profile.</p>
              <div className="row" style={{ marginTop: "10px" }}>
                <button
                  className="btn btn-primary"
                  onClick={() => send({ action: isRunning ? "stop" : "start" })}
                  disabled={(!loggedIn && !isRunning) || (!profileSaved && !isRunning)}
                >
                  {isRunning ? "Stop Agent" : "Start Applying"}
                </button>
              </div>
            </div>
          </div>

          <div className="stats-row">
            <div className="stat"><strong>{stats.evaluated}</strong>Evaluated</div>
            <div className="stat"><strong>{stats.applied}</strong>Applied</div>
            <div className="stat"><strong>{stats.skipped}</strong>Skipped</div>
            <div className="stat"><strong>{stats.already_applied}</strong>Already Applied</div>
            <div className="stat"><strong>{stats.current_query ? "Active" : "Idle"}</strong>{stats.current_query || "No query yet"}</div>
          </div>

          <div className="section">
            <h3>Job Results</h3>
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
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id}>
                      <td>{job.id}</td>
                      <td>{job.company}</td>
                      <td>{job.title}</td>
                      <td>{job.location}</td>
                      <td>{job.salary}</td>
                      <td>{job.experience}</td>
                      <td>{job.match_score == null ? "..." : `${job.match_score}%`}</td>
                      <td>{job.status}</td>
                    </tr>
                  ))}
                  {!jobs.length && (
                    <tr>
                      <td colSpan="8" style={{ textAlign: "center", color: "#777" }}>
                        No jobs evaluated yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="section">
            <h3>Activity Log</h3>
            <div className="log-box" ref={logBoxRef}>
              {logs.map((log, idx) => (
                <div className="log-line" key={`${log.time}-${idx}`}>
                  [{log.time}] {log.message}
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
