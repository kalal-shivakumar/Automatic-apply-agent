const { useEffect, useMemo, useRef, useState } = React;

const WS_URL = "ws://localhost:8000/ws";

const defaultProfile = {
  full_name: "",
  skills: [],
  job_titles: [],
  salary_min_lpa: "",
  salary_max_lpa: "",
  overall_experience_years: "",
  notice_period: "",
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

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function parseMatchScore(value) {
  if (value === null || value === undefined || value === "") return -1;
  const num = Number(String(value).replace(/[^\d.]/g, ""));
  return Number.isFinite(num) ? num : -1;
}

function formatStatusLines(job) {
  const statusText = String(job?.status || "").trim();
  const reasonText = String(job?.match_reason || "").trim();
  const scoreText = job?.match_score == null ? "" : `${job.match_score}%`;

  if (!statusText) return ["Pending", "Awaiting evaluation"];

  const selected = /applied|good match|selected|proceeding to apply/i.test(statusText);
  const skipped = /skip|skipped/i.test(statusText);
  const error = /error|failed/i.test(statusText);

  if (selected) {
    const reason = reasonText || (scoreText ? `Matched at ${scoreText}` : "Proceeding to apply");
    return ["Selected", reason];
  }
  if (skipped) {
    const reason = reasonText || (scoreText ? `Skipped at ${scoreText}` : "Below threshold or requirements mismatch");
    return ["Skipped", reason];
  }
  if (error) {
    return ["Error", reasonText || "Job evaluation failed"]; 
  }
  return ["Info", reasonText || statusText];
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
  const [linkedinBrowserLaunched, setLinkedinBrowserLaunched] = useState(false);
  const [linkedinLoggedIn, setLinkedinLoggedIn] = useState(false);
  const [linkedinIsRunning, setLinkedinIsRunning] = useState(false);

  const [jobs, setJobs] = useState([]);
  const [linkedinJobs, setLinkedinJobs] = useState([]);
  const [logs, setLogs] = useState([]);
  const [stats, setStats] = useState({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: "" });
  const [linkedinStats, setLinkedinStats] = useState({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: "" });

  const [resumeFile, setResumeFile] = useState(null);
  const [uploadPayload, setUploadPayload] = useState({ resumeText: "", fileBase64: "", mimeType: "" });
  const [resumeText, setResumeText] = useState("");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [profile, setProfile] = useState(defaultProfile);
  const [resumeSummary, setResumeSummary] = useState([]);
  const [profileSaved, setProfileSaved] = useState(false);
  const [homeMessage, setHomeMessage] = useState("");
  const [homeError, setHomeError] = useState("");
  const [jobSearchText, setJobSearchText] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("all");
  const [jobCompanyFilter, setJobCompanyFilter] = useState("");
  const [jobSortKey, setJobSortKey] = useState("id");
  const [jobSortDir, setJobSortDir] = useState("desc");
  const [linkedinSearchText, setLinkedinSearchText] = useState("");
  const [linkedinStatusFilter, setLinkedinStatusFilter] = useState("all");
  const [linkedinCompanyFilter, setLinkedinCompanyFilter] = useState("");
  const [linkedinSortKey, setLinkedinSortKey] = useState("id");
  const [linkedinSortDir, setLinkedinSortDir] = useState("desc");
  const [linkedinDebugLoading, setLinkedinDebugLoading] = useState(false);
  const [linkedinDebugError, setLinkedinDebugError] = useState("");
  const [linkedinDebugCapturedAt, setLinkedinDebugCapturedAt] = useState("");
  const [linkedinDebugReadiness, setLinkedinDebugReadiness] = useState({});
  const [linkedinDeepLoading, setLinkedinDeepLoading] = useState(false);
  const [linkedinDeepError, setLinkedinDeepError] = useState("");
  const [linkedinDeepReport, setLinkedinDeepReport] = useState(null);

  const wsRef = useRef(null);
  const reconnectRef = useRef(null);
  const logBoxRef = useRef(null);

  const skillsText = useMemo(() => (profile.skills || []).join(", "), [profile.skills]);
  const jobTitlesText = useMemo(() => (profile.job_titles || []).join(", "), [profile.job_titles]);
  const keywordText = useMemo(() => (profile.key_search_keywords || []).join(", "), [profile.key_search_keywords]);
  const locationText = useMemo(() => (profile.search_locations || []).join(", "), [profile.search_locations]);
  const noticePeriodValue = profile.notice_period || "";
  const profileSummaryItems = useMemo(() => ([
    { label: "Name", value: profile.full_name || "N/A" },
    { label: "Experience", value: profile.overall_experience_years ? `${profile.overall_experience_years} years` : "N/A" },
    { label: "Notice period", value: profile.notice_period || "N/A" },
    { label: "Salary range", value: profile.salary_min_lpa || profile.salary_max_lpa ? `${profile.salary_min_lpa || "?"}-${profile.salary_max_lpa || "?"} LPA` : "N/A" },
    { label: "Preferred location", value: profile.preferred_location || "N/A" },
    { label: "Ready to relocate", value: profile.ready_to_relocate ? "Yes" : "No" },
    { label: "Skills", value: skillsText || "N/A" },
    { label: "Job titles", value: jobTitlesText || "N/A" },
    { label: "Search keywords", value: keywordText || "N/A" },
    { label: "Search cities", value: locationText || "N/A" },
  ]), [profile, skillsText, jobTitlesText, keywordText, locationText]);

  const filteredAndSortedJobs = useMemo(() => {
    const search = normalizeText(jobSearchText);
    const companyFilter = normalizeText(jobCompanyFilter);

    const matches = (job) => {
      const haystack = [job.company, job.title, job.location, job.salary, job.experience, job.status, job.search_query]
        .map(normalizeText)
        .join(" ");
      if (search && !haystack.includes(search)) return false;
      if (companyFilter && !normalizeText(job.company).includes(companyFilter)) return false;
      if (jobStatusFilter !== "all") {
        const statusText = normalizeText(job.status);
        if (jobStatusFilter === "selected" && !/applied|good match|selected|proceeding to apply/.test(statusText)) return false;
        if (jobStatusFilter === "skipped" && !/skip|skipped/.test(statusText)) return false;
        if (jobStatusFilter === "error" && !/error|failed/.test(statusText)) return false;
      }
      return true;
    };

    const sortFactor = jobSortDir === "asc" ? 1 : -1;
    const sorted = [...jobs].filter(matches).sort((a, b) => {
      if (jobSortKey === "score") {
        return (parseMatchScore(a.match_score) - parseMatchScore(b.match_score)) * sortFactor;
      }
      if (jobSortKey === "company") {
        return normalizeText(a.company).localeCompare(normalizeText(b.company)) * sortFactor;
      }
      if (jobSortKey === "title") {
        return normalizeText(a.title).localeCompare(normalizeText(b.title)) * sortFactor;
      }
      if (jobSortKey === "salary") {
        return normalizeText(a.salary).localeCompare(normalizeText(b.salary)) * sortFactor;
      }
      if (jobSortKey === "status") {
        return normalizeText(a.status).localeCompare(normalizeText(b.status)) * sortFactor;
      }
      return ((Number(a.id) || 0) - (Number(b.id) || 0)) * sortFactor;
    });
    return sorted;
  }, [jobs, jobSearchText, jobStatusFilter, jobCompanyFilter, jobSortKey, jobSortDir]);

  const filteredAndSortedLinkedinJobs = useMemo(() => {
    const search = normalizeText(linkedinSearchText);
    const companyFilter = normalizeText(linkedinCompanyFilter);

    const matches = (job) => {
      const haystack = [job.company, job.title, job.location, job.salary, job.experience, job.status, job.search_query]
        .map(normalizeText)
        .join(" ");
      if (search && !haystack.includes(search)) return false;
      if (companyFilter && !normalizeText(job.company).includes(companyFilter)) return false;
      if (linkedinStatusFilter !== "all") {
        const statusText = normalizeText(job.status);
        if (linkedinStatusFilter === "selected" && !/applied|good match|selected|proceeding to apply/.test(statusText)) return false;
        if (linkedinStatusFilter === "skipped" && !/skip|skipped/.test(statusText)) return false;
        if (linkedinStatusFilter === "error" && !/error|failed/.test(statusText)) return false;
      }
      return true;
    };

    const sortFactor = linkedinSortDir === "asc" ? 1 : -1;
    const sorted = [...linkedinJobs].filter(matches).sort((a, b) => {
      if (linkedinSortKey === "score") {
        return (parseMatchScore(a.match_score) - parseMatchScore(b.match_score)) * sortFactor;
      }
      if (linkedinSortKey === "company") {
        return normalizeText(a.company).localeCompare(normalizeText(b.company)) * sortFactor;
      }
      if (linkedinSortKey === "title") {
        return normalizeText(a.title).localeCompare(normalizeText(b.title)) * sortFactor;
      }
      if (linkedinSortKey === "salary") {
        return normalizeText(a.salary).localeCompare(normalizeText(b.salary)) * sortFactor;
      }
      if (linkedinSortKey === "status") {
        return normalizeText(a.status).localeCompare(normalizeText(b.status)) * sortFactor;
      }
      return ((Number(a.id) || 0) - (Number(b.id) || 0)) * sortFactor;
    });
    return sorted;
  }, [linkedinJobs, linkedinSearchText, linkedinStatusFilter, linkedinCompanyFilter, linkedinSortKey, linkedinSortDir]);

  const toggleSortDir = (key) => {
    if (jobSortKey === key) {
      setJobSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setJobSortKey(key);
    setJobSortDir(key === "id" ? "desc" : "asc");
  };

  const toggleLinkedinSortDir = (key) => {
    if (linkedinSortKey === key) {
      setLinkedinSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setLinkedinSortKey(key);
    setLinkedinSortDir(key === "id" ? "desc" : "asc");
  };

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
        setLinkedinBrowserLaunched(Boolean(data.linkedin_browser_launched));
        setLinkedinLoggedIn(Boolean(data.linkedin_logged_in));
        setLinkedinIsRunning(Boolean(data.linkedin_is_running));
        if (Array.isArray(data.jobs)) setJobs(data.jobs);
        if (data.stats) setStats(data.stats);
        if (Array.isArray(data.linkedin_jobs)) setLinkedinJobs(data.linkedin_jobs);
        if (data.linkedin_stats) setLinkedinStats(data.linkedin_stats);
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
        setJobSearchText("");
        setJobStatusFilter("all");
        setJobCompanyFilter("");
        setJobSortKey("id");
        setJobSortDir("desc");
        setStats({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: "" });
        addLog(data.message || "Agent started.");
        break;

      case "linkedin_agent_started":
        setLinkedinIsRunning(true);
        setLinkedinJobs([]);
        setLinkedinSearchText("");
        setLinkedinStatusFilter("all");
        setLinkedinCompanyFilter("");
        setLinkedinSortKey("id");
        setLinkedinSortDir("desc");
        setLinkedinStats({ applied: 0, skipped: 0, already_applied: 0, evaluated: 0, current_query: "" });
        addLog(data.message || "LinkedIn agent started.");
        break;

      case "search_query":
        setStats((s) => ({
          ...s,
          current_query: `${data.keywords} in ${data.location} [${data.query_number}/${data.total_queries}]`,
        }));
        addLog(`Search ${data.query_number}/${data.total_queries}: ${data.keywords} in ${data.location}`);
        break;

      case "linkedin_search_query":
        setLinkedinStats((s) => ({
          ...s,
          current_query: `${data.keywords} in ${data.location} [${data.query_number}/${data.total_queries}]`,
        }));
        addLog(`LinkedIn ${data.query_number}/${data.total_queries}: ${data.keywords} in ${data.location}`);
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

      case "linkedin_job_update":
        setLinkedinJobs((prev) => {
          const index = prev.findIndex((j) => j.id === data.job.id);
          if (index >= 0) {
            const next = [...prev];
            next[index] = data.job;
            return next;
          }
          return [...prev, data.job];
        });
        if (data.stats) setLinkedinStats(data.stats);
        break;

      case "agent_completed":
      case "agent_stopped":
        setIsRunning(false);
        if (data.stats) setStats(data.stats);
        addLog(data.message || "Agent stopped.");
        break;

      case "linkedin_agent_completed":
      case "linkedin_agent_stopped":
        setLinkedinIsRunning(false);
        if (data.stats) setLinkedinStats(data.stats);
        addLog(data.message || "LinkedIn agent stopped.");
        break;

      case "linkedin_browser_status":
        setLinkedinBrowserLaunched(Boolean(data.launched));
        addLog(data.message || "LinkedIn browser status updated.");
        break;

      case "linkedin_login_status":
        setLinkedinLoggedIn(Boolean(data.logged_in));
        addLog(data.message || "LinkedIn login status updated.");
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

  const loadLinkedinDebugReadiness = async () => {
    setLinkedinDebugLoading(true);
    setLinkedinDebugError("");
    try {
      const res = await fetch("/linkedin/debug-readiness", { cache: "no-store" });
      const data = await res.json();
      if (!data.ok) {
        setLinkedinDebugReadiness({});
        setLinkedinDebugCapturedAt("");
        setLinkedinDebugError(data.message || "LinkedIn debug summary not available.");
        return;
      }
      setLinkedinDebugReadiness(data.automation_readiness || {});
      setLinkedinDebugCapturedAt(data.captured_at || "");
    } catch (_err) {
      setLinkedinDebugReadiness({});
      setLinkedinDebugCapturedAt("");
      setLinkedinDebugError("Failed to load LinkedIn debug summary.");
    } finally {
      setLinkedinDebugLoading(false);
    }
  };

  const loadLinkedinDeepInspection = async () => {
    setLinkedinDeepLoading(true);
    setLinkedinDeepError("");
    try {
      const res = await fetch("/linkedin/deep-inspection", { cache: "no-store" });
      const data = await res.json();
      if (!data.ok) {
        setLinkedinDeepReport(null);
        setLinkedinDeepError(data.message || "LinkedIn deep inspection not available.");
        return;
      }
      setLinkedinDeepReport(data.report || null);
    } catch (_err) {
      setLinkedinDeepReport(null);
      setLinkedinDeepError("Failed to load LinkedIn deep inspection report.");
    } finally {
      setLinkedinDeepLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "linkedin") {
      loadLinkedinDebugReadiness();
      loadLinkedinDeepInspection();
    }
  }, [activeTab]);

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
      notice_period: String(profile.notice_period || "").trim(),
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
        <p>Three-step flow: analyze HOME profile once, then run Naukri and LinkedIn auto-apply in parallel.</p>
        <div className="conn">
          <span className={`conn-dot ${connected ? "on" : ""}`} />
          {connected ? "Connected" : "Disconnected"}
        </div>
        <div className="tabs">
          <button className={`tab-btn ${activeTab === "home" ? "active" : ""}`} onClick={() => setActiveTab("home")}>HOME</button>
          <button className={`tab-btn ${activeTab === "apply" ? "active" : ""}`} onClick={() => setActiveTab("apply")}>Automatic Job Apply</button>
          <button className={`tab-btn ${activeTab === "linkedin" ? "active" : ""}`} onClick={() => setActiveTab("linkedin")}>LinkedIn Auto Apply</button>
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

          <div className="grid-2" style={{ marginTop: "12px" }}>
            <div className="field">
              <label>Notice period</label>
              <select
                value={noticePeriodValue}
                onChange={(e) => updateProfile("notice_period", e.target.value)}
              >
                <option value="">Select notice period</option>
                <option value="Immediate">Immediate</option>
                <option value="15 days">15 days</option>
                <option value="30 days">30 days</option>
                <option value="45 days">45 days</option>
                <option value="60 days">60 days</option>
                <option value="90 days">90 days</option>
              </select>
            </div>
            <div className="field">
              <label>Notice period guidance</label>
              <div className="helper">Pick the closest option so the recruiter Q&A can answer consistently.</div>
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

          <div className="summary-box profile-summary" style={{ marginBottom: "12px" }}>
            <h3>HOME values considered in this tab</h3>
            <div className="profile-summary-grid">
              {profileSummaryItems.map((item) => (
                <div className="profile-summary-item" key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          </div>

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
            <div className="table-controls">
              <input
                className="table-search"
                value={jobSearchText}
                onChange={(e) => setJobSearchText(e.target.value)}
                placeholder="Search company, title, location, salary, status..."
              />
              <input
                className="table-search"
                value={jobCompanyFilter}
                onChange={(e) => setJobCompanyFilter(e.target.value)}
                placeholder="Filter by company"
              />
              <select value={jobStatusFilter} onChange={(e) => setJobStatusFilter(e.target.value)}>
                <option value="all">All statuses</option>
                <option value="selected">Selected / Applied</option>
                <option value="skipped">Skipped</option>
                <option value="error">Error</option>
              </select>
              <div className="sort-group">
                <span>Sort by</span>
                <button className={`sort-btn ${jobSortKey === "id" ? "active" : ""}`} onClick={() => toggleSortDir("id")}>#</button>
                <button className={`sort-btn ${jobSortKey === "score" ? "active" : ""}`} onClick={() => toggleSortDir("score")}>Match</button>
                <button className={`sort-btn ${jobSortKey === "company" ? "active" : ""}`} onClick={() => toggleSortDir("company")}>Company</button>
                <button className={`sort-btn ${jobSortKey === "title" ? "active" : ""}`} onClick={() => toggleSortDir("title")}>Title</button>
                <button className={`sort-btn ${jobSortKey === "salary" ? "active" : ""}`} onClick={() => toggleSortDir("salary")}>Salary</button>
                <button className={`sort-btn ${jobSortKey === "status" ? "active" : ""}`} onClick={() => toggleSortDir("status")}>Status</button>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th role="button" tabIndex="0" onClick={() => toggleSortDir("id")}>#</th>
                    <th role="button" tabIndex="0" onClick={() => toggleSortDir("company")}>Company</th>
                    <th role="button" tabIndex="0" onClick={() => toggleSortDir("title")}>Job Title</th>
                    <th>Location</th>
                    <th role="button" tabIndex="0" onClick={() => toggleSortDir("salary")}>Salary</th>
                    <th>Experience</th>
                    <th role="button" tabIndex="0" onClick={() => toggleSortDir("score")}>Match</th>
                    <th role="button" tabIndex="0" onClick={() => toggleSortDir("status")}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAndSortedJobs.map((job) => {
                    const [statusTitle, statusReason] = formatStatusLines(job);
                    return (
                    <tr key={job.id}>
                      <td>{job.id}</td>
                      <td>{job.company}</td>
                      <td>
                        <a className="job-link" href={job.url || "#"} target="_blank" rel="noreferrer">
                          {job.title}
                        </a>
                      </td>
                      <td>{job.location}</td>
                      <td>{job.salary}</td>
                      <td>{job.experience}</td>
                      <td>{job.match_score == null ? "..." : `${job.match_score}%`}</td>
                      <td>
                        <div className="status-cell">
                          <div className="status-main">{statusTitle}</div>
                          <div className="status-sub">{statusReason}</div>
                        </div>
                      </td>
                    </tr>
                    );
                  })}
                  {!filteredAndSortedJobs.length && (
                    <tr>
                      <td colSpan="8" style={{ textAlign: "center", color: "#777" }}>
                        No jobs match the current filters.
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

      {activeTab === "linkedin" && (
        <section className="panel">
          <h2 className="card-title">LinkedIn Auto Apply</h2>

          <div className="summary-box" style={{ marginBottom: "12px" }}>
            <h3>Identify & Resolve First (LinkedIn)</h3>
            <div className="row" style={{ marginBottom: "8px" }}>
              <button className="btn btn-light" onClick={loadLinkedinDebugReadiness} disabled={linkedinDebugLoading}>
                {linkedinDebugLoading ? "Refreshing..." : "Refresh Debug Readiness"}
              </button>
              <button className="btn btn-light" onClick={loadLinkedinDeepInspection} disabled={linkedinDeepLoading}>
                {linkedinDeepLoading ? "Refreshing..." : "Refresh Deep Inspection"}
              </button>
              <div className="helper">
                {linkedinDebugCapturedAt ? `Last debug snapshot: ${linkedinDebugCapturedAt}` : "No debug snapshot loaded"}
              </div>
            </div>
            {linkedinDebugError && <div className="alert alert-warn">{linkedinDebugError}</div>}

            <div className="readiness-grid">
              {[
                ["linkedin_login", "1. LinkedIn login"],
                ["job_search", "2. Job search"],
                ["fields_detection", "3. Fields detection"],
                ["field_answering_strategy", "4. How to answer fields"],
                ["job_submission", "5. How to submit jobs"],
              ].map(([key, label]) => {
                const item = linkedinDebugReadiness[key] || {};
                const ok = Boolean(item.resolved);
                return (
                  <div className={`readiness-item ${ok ? "ok" : "pending"}`} key={key}>
                    <strong>{label}</strong>
                    <span>{ok ? "Resolved" : "Pending"}</span>
                    <p>{item.details || "Run debug_extract_linkedin_structure.py and refresh."}</p>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="summary-box" style={{ marginBottom: "12px" }}>
            <h3>Deep Inspection (Search -> Fields -> AI Answers -> Submit)</h3>
            {linkedinDeepError && <div className="alert alert-warn">{linkedinDeepError}</div>}
            {!linkedinDeepError && linkedinDeepReport && (
              <>
                <p>
                  Status: <strong>{linkedinDeepReport.ok ? "Ready" : "Blocked"}</strong> | Message: {linkedinDeepReport.message || "N/A"}
                </p>
                <p>
                  Jobs detected: <strong>{linkedinDeepReport?.job_search?.found_jobs ?? 0}</strong>
                  {" "} | Extracted fields: <strong>{linkedinDeepReport?.apply_flow?.extracted_field_count ?? 0}</strong>
                  {" "} | Submit controls: <strong>{linkedinDeepReport?.apply_flow?.submit_controls_detected ? "Detected" : "Not detected"}</strong>
                </p>
                {linkedinDeepReport?.apply_flow?.target_job && (
                  <p>
                    Target job: <strong>{linkedinDeepReport.apply_flow.target_job.title}</strong> at {linkedinDeepReport.apply_flow.target_job.company}
                  </p>
                )}
                {!!(linkedinDeepReport?.ai_answer_preview || []).length && (
                  <div className="table-wrap" style={{ maxHeight: "220px" }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Field Type</th>
                          <th>Question</th>
                          <th>AI Answer</th>
                        </tr>
                      </thead>
                      <tbody>
                        {linkedinDeepReport.ai_answer_preview.slice(0, 10).map((row, idx) => (
                          <tr key={`qa-preview-${idx}`}>
                            <td>{row.kind}</td>
                            <td>{row.question}</td>
                            <td>{row.ai_answer}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
            {!linkedinDeepError && !linkedinDeepReport && (
              <div className="helper">Run debug_linkedin_apply_flow.py and refresh this section.</div>
            )}
          </div>

          {!profileSaved ? (
            <div className="alert alert-warn">
              Please complete HOME tab and click Save Profile first. LinkedIn tab uses the same HOME values.
            </div>
          ) : (
            <div className="alert alert-ok">
              HOME profile loaded for LinkedIn: {profile.full_name || "Candidate"} | Experience: {profile.overall_experience_years || "N/A"} years | Salary: {profile.salary_min_lpa || "?"}-{profile.salary_max_lpa || "?"} LPA
            </div>
          )}

          <div className="summary-box profile-summary" style={{ marginBottom: "12px" }}>
            <h3>HOME values considered in this tab</h3>
            <div className="profile-summary-grid">
              {profileSummaryItems.map((item) => (
                <div className="profile-summary-item" key={`linkedin-${item.label}`}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="control-strip">
            <div className="ctrl">
              <h4>1. Launch LinkedIn Browser</h4>
              <p>Open dedicated LinkedIn login session.</p>
              <div className="row" style={{ marginTop: "10px" }}>
                <button
                  className="btn btn-light"
                  onClick={() => send({ action: "launch_browser_linkedin" })}
                  disabled={linkedinBrowserLaunched || linkedinIsRunning}
                >
                  {linkedinBrowserLaunched ? "Launched" : "Launch"}
                </button>
              </div>
            </div>
            <div className="ctrl">
              <h4>2. Verify LinkedIn Login</h4>
              <p>Confirm your manual login in browser.</p>
              <div className="row" style={{ marginTop: "10px" }}>
                <button
                  className="btn btn-light"
                  onClick={() => send({ action: "verify_login_linkedin" })}
                  disabled={!linkedinBrowserLaunched || linkedinLoggedIn || linkedinIsRunning}
                >
                  {linkedinLoggedIn ? "Verified" : "Verify"}
                </button>
              </div>
            </div>
            <div className="ctrl">
              <h4>3. Start / Stop LinkedIn Apply</h4>
              <p>Runs LinkedIn search and Easy Apply with AI answers.</p>
              <div className="row" style={{ marginTop: "10px" }}>
                <button
                  className="btn btn-primary"
                  onClick={() => send({ action: linkedinIsRunning ? "stop_linkedin" : "start_linkedin" })}
                  disabled={(!linkedinLoggedIn && !linkedinIsRunning) || (!profileSaved && !linkedinIsRunning)}
                >
                  {linkedinIsRunning ? "Stop LinkedIn Agent" : "Start LinkedIn Applying"}
                </button>
              </div>
            </div>
          </div>

          <div className="stats-row">
            <div className="stat"><strong>{linkedinStats.evaluated}</strong>Evaluated</div>
            <div className="stat"><strong>{linkedinStats.applied}</strong>Applied</div>
            <div className="stat"><strong>{linkedinStats.skipped}</strong>Skipped</div>
            <div className="stat"><strong>{linkedinStats.already_applied}</strong>Already Applied</div>
            <div className="stat"><strong>{linkedinStats.current_query ? "Active" : "Idle"}</strong>{linkedinStats.current_query || "No query yet"}</div>
          </div>

          <div className="section">
            <h3>LinkedIn Job Results</h3>
            <div className="table-controls">
              <input
                className="table-search"
                value={linkedinSearchText}
                onChange={(e) => setLinkedinSearchText(e.target.value)}
                placeholder="Search company, title, location, salary, status..."
              />
              <input
                className="table-search"
                value={linkedinCompanyFilter}
                onChange={(e) => setLinkedinCompanyFilter(e.target.value)}
                placeholder="Filter by company"
              />
              <select value={linkedinStatusFilter} onChange={(e) => setLinkedinStatusFilter(e.target.value)}>
                <option value="all">All statuses</option>
                <option value="selected">Selected / Applied</option>
                <option value="skipped">Skipped</option>
                <option value="error">Error</option>
              </select>
              <div className="sort-group">
                <span>Sort by</span>
                <button className={`sort-btn ${linkedinSortKey === "id" ? "active" : ""}`} onClick={() => toggleLinkedinSortDir("id")}>#</button>
                <button className={`sort-btn ${linkedinSortKey === "score" ? "active" : ""}`} onClick={() => toggleLinkedinSortDir("score")}>Match</button>
                <button className={`sort-btn ${linkedinSortKey === "company" ? "active" : ""}`} onClick={() => toggleLinkedinSortDir("company")}>Company</button>
                <button className={`sort-btn ${linkedinSortKey === "title" ? "active" : ""}`} onClick={() => toggleLinkedinSortDir("title")}>Title</button>
                <button className={`sort-btn ${linkedinSortKey === "salary" ? "active" : ""}`} onClick={() => toggleLinkedinSortDir("salary")}>Salary</button>
                <button className={`sort-btn ${linkedinSortKey === "status" ? "active" : ""}`} onClick={() => toggleLinkedinSortDir("status")}>Status</button>
              </div>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th role="button" tabIndex="0" onClick={() => toggleLinkedinSortDir("id")}>#</th>
                    <th role="button" tabIndex="0" onClick={() => toggleLinkedinSortDir("company")}>Company</th>
                    <th role="button" tabIndex="0" onClick={() => toggleLinkedinSortDir("title")}>Job Title</th>
                    <th>Location</th>
                    <th role="button" tabIndex="0" onClick={() => toggleLinkedinSortDir("salary")}>Salary</th>
                    <th>Experience</th>
                    <th role="button" tabIndex="0" onClick={() => toggleLinkedinSortDir("score")}>Match</th>
                    <th role="button" tabIndex="0" onClick={() => toggleLinkedinSortDir("status")}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAndSortedLinkedinJobs.map((job) => {
                    const [statusTitle, statusReason] = formatStatusLines(job);
                    return (
                      <tr key={`linkedin-${job.id}`}>
                        <td>{job.id}</td>
                        <td>{job.company}</td>
                        <td>
                          <a className="job-link" href={job.url || "#"} target="_blank" rel="noreferrer">
                            {job.title}
                          </a>
                        </td>
                        <td>{job.location}</td>
                        <td>{job.salary}</td>
                        <td>{job.experience}</td>
                        <td>{job.match_score == null ? "..." : `${job.match_score}%`}</td>
                        <td>
                          <div className="status-cell">
                            <div className="status-main">{statusTitle}</div>
                            <div className="status-sub">{statusReason}</div>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {!filteredAndSortedLinkedinJobs.length && (
                    <tr>
                      <td colSpan="8" style={{ textAlign: "center", color: "#777" }}>
                        No LinkedIn jobs match the current filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
