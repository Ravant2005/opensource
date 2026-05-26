// Main entry point for the React app
// Using UMD builds from CDN, accessed via window globals

// Helper function to fetch data from the API
async function fetchAPI(endpoint, options = {}) {
  const token = localStorage.getItem('token') || '';
  const headers = {
    'Content-Type': 'application/json',
    ...(token && { 'Authorization': `Bearer ${token}` }),
    ...options.headers,
  };
  const response = await fetch(`http://127.0.0.1:8001/api/v1${endpoint}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json();
}

// ======================
// Layout Component
// ======================
function Layout({ children }) {
  return (
    <div>
      <header>
        <h1>OCIS Dashboard</h1>
        <nav>
          <Link to="/" className="btn btn-secondary">Home</Link>
          <Link to="/jobs" className="btn btn-secondary ml-2">Jobs</Link>
          <Link to="/resume" className="btn btn-secondary ml-2">Resume</Link>
        </nav>
      </header>
      <div className="container">{children}</div>
    </div>
  );
}

// ======================
// Reusable Components
// ======================
function Card({ children, title }) {
  return (
    <div className="card">
      {title && <h3>{title}</h3>}
      {children}
    </div>
  );
}

function Button({ children, onClick, variant = 'primary', disabled = false }) {
  const baseClass = 'btn';
  const variantClass = variant === 'secondary' ? 'btn-secondary' : '';
  return (
    <button
      className={`${baseClass} ${variantClass}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function Badge({ children, variant = 'default' }) {
  const baseClass = 'badge';
  const variantClass = {
    'default': '',
    'success': 'bg-success',
    'warning': 'bg-warning',
    'error': 'bg-error',
  }[variant] || '';
  return (
    <span className={`${baseClass} ${variantClass}`}>
      {children}
    </span>
  );
}

// ======================
// Home Page
// ======================
function Home() {
  const [repos, setRepos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [repoUrl, setRepoUrl] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAPI('/jobs', {
        method: 'POST',
        body: JSON.stringify({ repo_url: repoUrl, dry_run: true }),
      });
      // In a real app, we would redirect to the job page
      alert(`Job submitted! Job ID: ${response.job_id}`);
      setRepoUrl('');
      // Optionally, refresh the job list
      loadJobs();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadJobs = async () => {
    try {
      const data = await fetchAPI('/jobs');
      setRepos(data.jobs);
    } catch (err) {
      setError('Failed to load jobs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadJobs();
  }, []);

  if (loading) return <div className="loading">Loading...</div>;
  if (error) return <div className="error">Error: {error}</div>;

  return (
    <Card>
      <h2>Analyse a Repository</h2>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="repoUrl">GitHub Repository URL:</label>
          <input
            type="text"
            id="repoUrl"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            required
            className="input"
          />
        </div>
        <Button type="submit" variant="primary">
          Analyse
        </Button>
      </form>

      <h2>Recent Jobs</h2>
      {repos.length === 0 ? (
        <p>No jobs yet. Submit a repository to get started.</p>
      ) : (
        <ul>
          {repos.map((job) => (
            <li key={job.job_id}>
              <Link to={`/job/${job.job_id}`}>
                {job.repo_slug} - {job.status} ({job.progress}%)
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ======================
// Job View Page
// ======================
function JobView() {
  const { job_id } = useParams();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const loadJob = async () => {
      setLoading(true);
      try {
        const data = await fetchAPI(`/jobs/${job_id}`);
        setJob(data);
      } catch (err) {
        setError('Failed to load job');
      } finally {
        setLoading(false);
      }
    };

    loadJob();

    // Set up polling for updates
    const interval = setInterval(loadJob, 5000);
    return () => clearInterval(interval);
  }, [job_id]);

  if (loading) return <div className="loading">Loading job...</div>;
  if (error) return <div className="error">Error: {error}</div>;
  if (!job) return <div className="error">Job not found</div>;

  return (
    <>
      <Card title={`Job: ${job.repo_slug}`}>
        <p>
          Status: <strong>{job.status}</strong> | Progress: {job.progress}%
        </p>

        {job.status === 'awaiting_hitl' && (
          <div>
            <Button
              onClick={() => navigate(`/job/${job_id}/review`)}
              variant="secondary"
            >
              Go to Review
            </Button>
          </div>
        )}

        {job.status === 'executing' && (
          <div>
            <p>The system is implementing the approved contributions.</p>
          </div>
        )}

        {job.status === 'done' && (
          <div>
            <p>
              {job.pr_results.length} PR(s) processed.
              {job.pr_results.filter((r) => r.success).length} successful.
            </p>
            <Button
              onClick={() => navigate(`/job/${job_id}/results`)}
              variant="primary"
            >
              View Results
            </Button>
          </div>
        )}
      </Card>

      <Card title="Live Logs">
        <LogStream job_id={job_id} />
      </Card>
    </>
  );
}

// ======================
// Log Stream Component (SSE)
// ======================
function LogStream({ job_id }) {
  const [logs, setLogs] = useState([]);
  const [since, setSince] = useState(0);
  const [status, setStatus] = useState(null);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const eventSource = new EventSource(
      `http://127.0.0.1:8001/api/v1/jobs/${job_id}/logs?since=${since}`
    );

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.status) {
          // Status update
          setStatus(data.status);
          setProgress(data.progress);
        } else {
          setLogs((prev) => [...prev, data]);
          setSince((prev) => prev + 1);
        }
      } catch (e) {
        console.error('Failed to parse log event:', e);
      }
    };

    eventSource.onerror = (event) => {
      console.error('SSE error:', event);
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [job_id, since]);

  return (
    <div style={{ height: '300px', overflowY: 'auto', backgroundColor: '#161b22', padding: '1rem', borderRadius: '4px' }}>
      {status && (
        <div style={{ marginBottom: '0.5rem' }}>
          <strong>Status:</strong> {status} ({progress}%)
        </div>
      )}
      {logs.map((log, index) => (
        <div key={index} style={{ marginBottom: '0.5rem', fontFamily: 'monospace', fontSize: '0.9rem' }}>
          <span style={{ color: '#8b949e' }}>{new Date(log.ts).toLocaleTimeString()}</span>
          <span style={{ color: log.level === 'ERROR' ? '#f85149' : '#c9d1d9' }}>{log.msg}</span>
        </div>
      ))}
    </div>
  );
}

// ======================
// Review Page (HiTL)
// ======================
function ReviewPage() {
  const { job_id } = useParams();
  const [jobData, setJobData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      try {
        const data = await fetchAPI(`/jobs/${job_id}/review`);
        setJobData(data);
      } catch (err) {
        setError('Failed to load review data');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [job_id]);

  if (loading) return <div className="loading">Loading review data...</div>;
  if (error) return <div className="error">Error: {error}</div>;
  if (!jobData) return <div className="error">No data available</div>;

  const handleApprove = async (e) => {
    e.preventDefault();
    const approvedIds = Array.from(
      e.target.querySelectorAll('input[name="approved"]:checked')
    ).map((input) => input.value);

    try {
      await fetchAPI(`/jobs/${job_id}/approve`, {
        method: 'POST',
        body: JSON.stringify({ approved_ids: approvedIds }),
      });
      alert('Recommendations approved!');
      // In a real app, we might redirect to the execution page or back to the job
    } catch (err) {
      setError('Failed to approve recommendations');
    }
  };

  return (
    <>
      <Card title={`Review Recommendations for ${jobData.repo_slug}`}>
        <div className="card">
          <p><strong>Project:</strong> {jobData.intelligence_summary.project_name || 'N/A'}</p>
          <p><strong>Description:</strong> {jobData.intelligence_summary.synthesis?.project_summary || 'N/A'}</p>
        </div>
      </Card>

      <form onSubmit={handleApprove}>
        <Card title="Recommendations">
          {jobData.recommendations.length === 0 ? (
            <p>No recommendations generated.</p>
          ) : (
            <ul>
              {jobData.recommendations.map((rec) => {
                const opp = rec.opportunity || {};
                return (
                  <li key={opp.id || Math.random()} style={{ marginBottom: '1.5rem', paddingBottom: '1rem', borderBottom: '1px solid #30363d' }}>
                    <h4>
                      {opp.title} <Badge variant="default">{opp.type || 'unknown'}</Badge>
                    </h4>
                    <p>
                      <strong>Impact:</strong> {opp.impact_score?.toFixed(1) || 'N/A'} | 
                      <strong>Difficulty:</strong> {opp.difficulty_score?.toFixed(1) || 'N/A'} | 
                      <strong>Novelty:</strong> {opp.novelty_score?.toFixed(1) || 'N/A'}
                    </p>
                    <p>{opp.description || 'No description available.'}</p>
                    <div style={{ marginTop: '0.5rem' }}>
                      <label>
                        <input
                          type="checkbox"
                          name="approved"
                          value={opp.id}
                          defaultChecked
                        />
                        Approve this recommendation
                      </label>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Button type="submit" variant="primary" style={{ marginTop: '1rem' }}>
          Approve Selected and Execute
        </Button>
      </form>
    </>
  );
}

// ======================
// Results Page
// ======================
function ResultsPage() {
  const { job_id } = useParams();
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const loadResults = async () => {
      setLoading(true);
      try {
        const data = await fetchAPI(`/jobs/${job_id}/results`);
        setResults(data);
      } catch (err) {
        setError('Failed to load results');
      } finally {
        setLoading(false);
      }
    };

    loadResults();
  }, [job_id]);

  if (loading) return <div className="loading">Loading results...</div>;
  if (error) return <div className="error">Error: {error}</div>;
  if (!results) return <div className="error">No results available</div>;

  return (
    <>
      <Card title={`Results for ${results.repo_slug}`}>
        <p>
          Status: <strong>{results.status}</strong>
        </p>
      </Card>

      {results.pr_results.length === 0 ? (
        <Card>No PRs were processed.</Card>
      ) : (
        <Card title="PR Results">
          <ul>
            {results.pr_results.map((pr, index) => (
              <li key={index} style={{ marginBottom: '1rem', paddingBottom: '1rem', borderBottom: '1px solid #30363d' }}>
                <h4>{pr.recommendation_title || `PR #${index + 1}`}</h4>
                <p>
                  Status: <strong>{pr.success ? 'Success' : 'Failed'}</strong>
                </p>
                {!pr.success && pr.error && (
                  <p style={{ color: '#f85149' }}>Error: {pr.error}</p>
                )}
                {pr.pr_result && pr.pr_result.pr_url && (
                  <p>
                    <a href={pr.pr_result.pr_url} target="_blank" rel="noopener noreferrer">
                      View PR
                    </a>
                  </p>
                )}
                {pr.resume_bullet && (
                  <Card title="Resume Bullet" style={{ marginTop: '0.5rem' }}>
                    <p>{pr.resume_bullet}</p>
                  </Card>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

// ======================
// Resume Page
// ======================
function ResumePage() {
  const [bullets, setBullets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const loadResume = async () => {
      setLoading(true);
      try {
        const data = await fetchAPI('/resume');
        setBullets(data.bullets);
      } catch (err) {
        setError('Failed to load resume bullets');
      } finally {
        setLoading(false);
      }
    };

    loadResume();
  }, []);

  if (loading) return <div className="loading">Loading resume...</div>;
  if (error) return <div className="error">Error: {error}</div>;

  return (
    <Card title="OCIS Generated Resume Bullets">
      {bullets.length === 0 ? (
        <p>No successful PRs yet. Run some jobs to generate resume bullets.</p>
      ) : (
        <ul>
          {bullets.map((bullet, index) => (
            <li key={index}>
              <strong>{bullet.repo_slug}:</strong> {bullet.bullet}
              {bullet.pr_url && (
                <>
                  <br />
                  <a href={bullet.pr_url} target="_blank" rel="noopener noreferrer">
                    PR Link
                  </a>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ======================
// App Router
// ======================
function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/jobs" element={<Home />} /> {/* Redirect to home for now */}
          <Route path="/job/:job_id" element={<JobView />} />
          <Route path="/job/:job_id/review" element={<ReviewPage />} />
          <Route path="/job/:job_id/results" element={<ResultsPage />} />
          <Route path="/resume" element={<ResumePage />} />
          <Route path="*" element={<div className="error">404 - Page not found</div>} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

// Set up React and ReactDOM from globals
const { useState, useEffect } = React;
const { BrowserRouter, Routes, Route, Link, useNavigate, useParams } = ReactRouterDOM;

// Render the app
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);