// Minimal UMD React dashboard (no JSX, no Babel, no react-router)
// Hash routing: #/ , #/job/{id} , #/job/{id}/review
;(function () {
  const React = window.React;
  const ReactDOM = window.ReactDOM;
  const { useState, useEffect, useRef } = React;

  function fetchAPI(endpoint, options) {
    options = options || {};
    const token = localStorage.getItem('token') || '';
    const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch('/api/v1' + endpoint, Object.assign({}, options, { headers }))
      .then(function (resp) {
        if (!resp.ok) return resp.text().then(function (t) { throw new Error('API ' + resp.status + ': ' + t); });
        try { return resp.json(); } catch (e) { return resp.text(); }
      });
  }

  function createEl(tag, props) {
    props = props || {};
    var children = Array.prototype.slice.call(arguments, 2);
    return React.createElement.apply(null, [tag, props].concat(children));
  }

  function Layout(props) {
    var children = props.children;
    return createEl('div', null,
      createEl('header', { style: { backgroundColor: '#161b22', padding: '12px', borderBottom: '1px solid #30363d' } },
        createEl('h1', { style: { margin: 0, color: '#00ff9f' } }, 'OCIS Dashboard'),
        createEl('nav', { style: { marginTop: '8px' } },
          createEl('a', { href: '#/', style: { marginRight: '8px', color: '#c9d1d9' } }, 'Home'),
          createEl('a', { href: '#/jobs', style: { marginRight: '8px', color: '#c9d1d9' } }, 'Jobs'),
          createEl('a', { href: '#/resume', style: { color: '#c9d1d9' } }, 'Resume')
        )
      ),
      createEl('div', { style: { padding: '18px', maxWidth: '1100px', margin: '0 auto' } }, children)
    );
  }

  function Card(title) {
    var header = title ? createEl('h3', null, title) : null;
    var children = Array.prototype.slice.call(arguments, 1);
    var props = { style: { backgroundColor: '#161b22', borderRadius: '8px', padding: '16px', marginBottom: '12px', border: '1px solid #30363d' } };
    return React.createElement.apply(null, [ 'div', props, header ].concat(children));
  }

  function Home() {
    var _a = useState([]), jobs = _a[0], setJobs = _a[1];
    var _b = useState(false), loading = _b[0], setLoading = _b[1];
    var _c = useState(''), repoUrl = _c[0], setRepoUrl = _c[1];
    var _d = useState(null), error = _d[0], setError = _d[1];

    useEffect(function () {
      setLoading(true);
      fetchAPI('/jobs').then(function (d) { setJobs(d.jobs || []); }).catch(function (e) { setError(e.message); }).finally(function () { setLoading(false); });
    }, []);

    function submit(e) {
      e.preventDefault();
      setLoading(true);
      fetchAPI('/jobs', { method: 'POST', body: JSON.stringify({ repo_url: repoUrl }) })
        .then(function (r) {
          setRepoUrl('');
          window.location.hash = '#/job/' + r.job_id;  // go directly to live log view
        })
        .catch(function (err) { setError(err.message); })
        .finally(function () { setLoading(false); });
    }

    if (loading) return Card(null, createEl('div', { style: { color: '#8b949e' } }, 'Loading...'));
    if (error) return Card('Error', createEl('div', null, error));

    return Card('Analyse a Repository',
      createEl('form', { onSubmit: submit },
        createEl('div', null,
          createEl('label', { htmlFor: 'repoUrl' }, 'GitHub Repository URL:'),
          createEl('input', { id: 'repoUrl', type: 'text', value: repoUrl, onChange: function (e) { setRepoUrl(e.target.value); }, placeholder: 'https://github.com/owner/repo', required: true, style: { width: '70%', padding: '8px', marginRight: '8px' } }),
          createEl('button', { type: 'submit', style: { backgroundColor: '#00ff9f', border: 'none', padding: '8px 12px', cursor: 'pointer' } }, 'Analyse')
        )
      ),
      createEl('h2', null, 'Recent Jobs'),
      jobs.length === 0 ? createEl('p', null, 'No jobs yet.') : createEl('ul', null, jobs.map(function (j) { return createEl('li', { key: j.job_id }, createEl('a', { href: '#/job/' + j.job_id }, j.repo_slug + ' - ' + j.status + ' (' + (j.progress || 0) + '%)')); }))
    );
  }

  function JobView(props) {
    var jobId = props.jobId;
    var _a = useState(null), job = _a[0], setJob = _a[1];
    var _b = useState([]), logs = _b[0], setLogs = _b[1];
    var _c = useState(true), loading = _c[0], setLoading = _c[1];
    var _d = useState(null), error = _d[0], setError = _d[1];

    var logEndRef = useRef(null);

    useEffect(function() {
      if (logEndRef.current) {
        logEndRef.current.scrollIntoView({ behavior: 'smooth' });
      }
    }, [logs]);

    useEffect(function () {
      var mounted = true;
      function load(isInitial) {
        if (isInitial) setLoading(true);
        fetchAPI('/jobs/' + jobId)
          .then(function (d) { 
            if (mounted) { 
              setJob(d); 
              setError(null);
              // If job is already in terminal state, we might need to fetch logs via regular API 
              // because EventSource might have missed them or closed.
              if (d.logs && d.logs.length > logs.length) {
                setLogs(d.logs);
              }
            } 
          })
          .catch(function (e) {
            if (mounted) {
              if (e.message.indexOf('404') !== -1) {
                setError('Job not found. If you recently restarted the server, in-memory jobs are lost. Please go back and submit the repository again.');
              } else {
                setError(e.message);
              }
            }
          })
          .finally(function () { if (mounted && isInitial) setLoading(false); });
      }
      load(true);
      var iv = setInterval(function() { load(false); }, 5000);
      return function () { mounted = false; clearInterval(iv); };
    }, [jobId]);

    useEffect(function () {
      var eventSource = new EventSource('/api/v1/jobs/' + jobId + '/logs');
      eventSource.onmessage = function (event) {
        try {
          var entry = JSON.parse(event.data);
          if (entry.msg) {
            setLogs(function (prev) { 
              // Avoid duplicates if load() also fetched them
              if (prev.some(function(l) { return l.msg === entry.msg && l.ts === entry.ts; })) return prev;
              return prev.concat([entry]); 
            });
          }
        } catch (e) {
          // Ignore non-json data
        }
      };
      eventSource.onerror = function () {
        eventSource.close();
      };
      return function () {
        eventSource.close();
      };
    }, [jobId]);

    if (loading) return createEl(Layout, null, Card(null, createEl('div', { style: { color: '#8b949e' } }, 'Loading job...')));
    if (error) return createEl(Layout, null, Card('Error',
      createEl('div', null,
        createEl('p', { style: { color: '#f85149', marginBottom: '16px' } }, error),
        createEl('a', { href: '#/', style: { color: '#00b4d8', textDecoration: 'underline' } }, '← Back to Home to submit again')
      )
    ));
    if (!job) return createEl(Layout, null, Card('Error', createEl('div', null, 'Job not found')));

    // Phase badge colours
    var phaseColor = {
      submitted: '#8b949e', gathering: '#f0a500', analyzing: '#f0a500',
      correlating: '#f0a500', recommending: '#f0a500',
      awaiting_hitl: '#00ff9f', executing: '#00b4d8',
      done: '#00ff9f', failed: '#f85149',
    }[job.status] || '#8b949e';

    var phases = ['submitted','gathering','analyzing','correlating','recommending','awaiting_hitl','executing','done'];
    var phaseIdx = phases.indexOf(job.status);

    // Phase progress bar
    var progressBar = createEl('div', { style: { marginBottom: '20px' } },
      createEl('div', { style: { display: 'flex', gap: '4px', marginBottom: '8px' } },
        phases.slice(0, 7).map(function(p, i) {
          var done = i <= phaseIdx;
          var active = i === phaseIdx;
          return createEl('div', { key: p, title: p, style: {
            flex: 1, height: '8px', borderRadius: '4px',
            backgroundColor: done ? '#00ff9f' : '#30363d',
            boxShadow: active ? '0 0 10px #00ff9f' : 'none',
            transition: 'all 0.4s',
          }});
        })
      ),
      createEl('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
        createEl('div', null,
          createEl('span', { 
            className: job.status !== 'done' && job.status !== 'failed' ? 'pulse' : '',
            style: { color: phaseColor, fontWeight: 'bold', fontSize: '18px' } 
          }, job.status.toUpperCase()),
          createEl('span', { style: { color: '#8b949e', marginLeft: '12px' } }, job.progress + '%')
        ),
        createEl('div', { style: { color: '#8b949e', fontSize: '12px' } }, 'Updated: ' + new Date().toLocaleTimeString())
      )
    );

    // Last Activity
    var lastLog = logs.length > 0 ? logs[logs.length - 1] : null;
    var activityFeed = lastLog ? createEl('div', {
      style: { backgroundColor: '#161b22', borderLeft: '4px solid #00ff9f', padding: '12px', marginBottom: '20px', borderRadius: '0 8px 8px 0' }
    },
      createEl('div', { style: { color: '#8b949e', fontSize: '11px', marginBottom: '4px' } }, 'CURRENT ACTIVITY'),
      createEl('div', { style: { color: '#e6edf3', fontSize: '14px', fontWeight: 'bold' } }, lastLog.msg)
    ) : null;

    // Intelligence summary (shown once available)
    var intel = job.intelligence || {};
    var synthesis = intel.synthesis || {};
    var meta = (intel.github || {}).metadata || {};
    var intelCard = meta.name ? createEl('div', {
      style: { backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '8px', padding: '16px', marginBottom: '20px' }
    },
      createEl('h4', { style: { color: '#00b4d8', margin: '0 0 12px', borderBottom: '1px solid #30363d', paddingBottom: '8px' } }, '📊 Intelligence Summary'),
      createEl('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px', marginBottom: '15px' } },
        createEl('div', null, createEl('div', { style: { color: '#8b949e', fontSize: '11px' } }, 'STARS'), createEl('div', null, '⭐ ' + (meta.stars || 0))),
        createEl('div', null, createEl('div', { style: { color: '#8b949e', fontSize: '11px' } }, 'FORKS'), createEl('div', null, '🍴 ' + (meta.forks || 0))),
        createEl('div', null, createEl('div', { style: { color: '#8b949e', fontSize: '11px' } }, 'LANGUAGE'), createEl('div', null, meta.language || 'N/A'))
      ),
      synthesis.project_summary ? createEl('p', { style: { color: '#8b949e', marginBottom: '15px', lineHeight: '1.5' } }, synthesis.project_summary) : null,
      synthesis.top_pain_points && synthesis.top_pain_points.length
        ? createEl('div', null,
            createEl('strong', { style: { fontSize: '12px', color: '#f0a500' } }, 'TOP PAIN POINTS'),
            createEl('ul', { style: { margin: '8px 0', paddingLeft: '18px', color: '#8b949e' } },
              synthesis.top_pain_points.slice(0, 3).map(function(pp, i) {
                return createEl('li', { key: i, style: { marginBottom: '4px' } }, pp.title || pp);
              })
            )
          )
        : null
    ) : null;

    return Card('Job ' + jobId,
      progressBar,
      createEl('p', { style: { marginBottom: '20px' } }, 'Repository: ', createEl('strong', { style: { color: '#58a6ff' } }, job.repo_slug)),
      activityFeed,
      intelCard,
      job.status === 'awaiting_hitl' || job.status === 'done'
        ? createEl('div', { style: { textAlign: 'center', margin: '20px 0' } },
            createEl('a', {
              href: '#/job/' + jobId + '/review',
              className: 'glow-button',
              style: { 
                display: 'inline-block', backgroundColor: '#00ff9f', color: '#0d1117',
                padding: '12px 24px', borderRadius: '8px', fontWeight: 'bold', textDecoration: 'none',
                boxShadow: '0 0 15px rgba(0, 255, 159, 0.4)', fontSize: '16px'
              }
            }, '🚀 Review & Approve Contributions (' + (job.recommendations || []).length + ')')
          )
        : null,
      createEl('div', { style: { marginTop: '30px' } },
        createEl('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' } },
          createEl('h4', { style: { margin: 0, color: '#8b949e' } }, 'LIVE CONSOLE OUTPUT'),
          createEl('span', { style: { fontSize: '11px', color: '#8b949e' } }, logs.length + ' entries')
        ),
        createEl('div', { 
          style: { 
            backgroundColor: '#010409', border: '1px solid #30363d', borderRadius: '8px',
            padding: '0', overflow: 'hidden'
          }
        },
          React.createElement.apply(null, [
            'pre', 
            { 
              style: { 
                whiteSpace: 'pre-wrap', maxHeight: '400px', overflow: 'auto',
                margin: 0, padding: '15px',
                fontSize: '12px', color: '#d1d5db', fontFamily: '"JetBrains Mono", monospace'
              } 
            }
          ].concat(logs.map(function (e, i) { 
              var color = e.level === 'ERROR' ? '#f85149' : (e.level === 'WARNING' ? '#f0a500' : '#8b949e');
              return createEl('div', { key: i, style: { marginBottom: '2px', borderBottom: '1px solid #161b22', paddingBottom: '2px' } },
                createEl('span', { style: { color: color, marginRight: '8px', fontSize: '10px' } }, '[' + (e.level || 'INFO') + ']'),
                createEl('span', { style: { color: '#8b949e', marginRight: '8px', fontSize: '10px' } }, new Date(e.ts).toLocaleTimeString()),
                createEl('span', null, e.msg)
              );
            })).concat([createEl('div', { ref: logEndRef })])
          )
        )
      )
    );
  }

  function ReviewView(props) {
    var jobId = props.jobId;
    var _a = useState(null), data = _a[0], setData = _a[1];
    var _b = useState(true), loading = _b[0], setLoading = _b[1];
    var _c = useState(null), error = _c[0], setError = _c[1];
    var _d = useState([]), approvedIds = _d[0], setApprovedIds = _d[1];
    var _e = useState(false), submitting = _e[0], setSubmitting = _e[1];
    var _f = useState(null), message = _f[0], setMessage = _f[1];

    function getRecId(rec, idx) {
      return (rec.opportunity && rec.opportunity.id) || ('rec_' + idx);
    }

    function loadReview() {
      setLoading(true);
      setError(null);
      fetchAPI('/jobs/' + jobId + '/review')
        .then(function (r) {
          setData(r);
          var ids = (r.recommendations || []).map(function (rec, idx) { return getRecId(rec, idx); });
          setApprovedIds(ids);
        })
        .catch(function (e) { setError(e.message); })
        .finally(function () { setLoading(false); });
    }

    function toggleApproval(id) {
      if (approvedIds.indexOf(id) === -1) {
        setApprovedIds(approvedIds.concat([id]));
      } else {
        setApprovedIds(approvedIds.filter(function (value) { return value !== id; }));
      }
    }

    function approveSelected() {
      setSubmitting(true);
      setError(null);
      fetchAPI('/jobs/' + jobId + '/approve', {
        method: 'POST',
        body: JSON.stringify({ approved_ids: approvedIds }),
      })
        .then(function (r) {
          setMessage('Approved ' + r.approved_count + ' recommendation(s).');
          loadReview();
        })
        .catch(function (e) { setError(e.message); })
        .finally(function () { setSubmitting(false); });
    }

    function executeApproved() {
      setSubmitting(true);
      setError(null);
      fetchAPI('/jobs/' + jobId + '/execute', {
        method: 'POST',
        body: JSON.stringify({ }),
      })
        .then(function (r) {
          setMessage('Execution started. Returning to job status view.');
          window.location.hash = '#/job/' + jobId;
        })
        .catch(function (e) { setError(e.message); })
        .finally(function () { setSubmitting(false); });
    }

    useEffect(function () {
      loadReview();
    }, [jobId]);

    if (loading) return createEl(Layout, null, Card(null, createEl('div', { style: { color: '#8b949e' } }, 'Loading review...')));
    if (error) return createEl(Layout, null, Card('Error',
      createEl('div', null,
        createEl('p', { style: { color: '#f85149', marginBottom: '16px' } }, error),
        createEl('a', { href: '#/', style: { color: '#00b4d8', textDecoration: 'underline' } }, '← Back to Home')
      )
    ));
    if (!data) return createEl(Layout, null, Card('No data', createEl('div', null, 'No recommendations')));

    var terminalStatuses = ['awaiting_hitl', 'executing', 'done', 'failed'];
    if (data && terminalStatuses.indexOf(data.status) === -1) {
      return Card('Analysis in progress',
        createEl('div', null,
          createEl('p', { style: { color: '#8b949e' } },
            'Job is currently in phase: ' + data.status + '. Recommendations will appear here once Phase 4 completes.'
          ),
          createEl('a', { href: '#/job/' + jobId, style: { color: '#00b4d8' } }, '← Back to live log')
        )
      );
    }

    var synthesis = (data.intelligence_summary && data.intelligence_summary.synthesis) || {};
    var ghMeta = (data.intelligence_summary && data.intelligence_summary.metadata) || {};

    var intelPanel = createEl('div', {
      style: { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: '20px' }
    },
      // Pain points card
      createEl('div', { style: { backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '8px', padding: '12px' } },
        createEl('h4', { style: { color: '#f85149', margin: '0 0 8px', fontSize: '13px' } }, '🔥 Community Pain Points'),
        synthesis.top_pain_points && synthesis.top_pain_points.length
          ? createEl('ul', { style: { margin: 0, paddingLeft: '16px', color: '#8b949e', fontSize: '12px' } },
              synthesis.top_pain_points.slice(0, 4).map(function(pp, i) {
                return createEl('li', { key: i, style: { marginBottom: '4px' } }, pp.title || pp);
              })
            )
          : createEl('p', { style: { color: '#8b949e', fontSize: '12px' } }, 'No data')
      ),
      // Roadmap card
      createEl('div', { style: { backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '8px', padding: '12px' } },
        createEl('h4', { style: { color: '#00b4d8', margin: '0 0 8px', fontSize: '13px' } }, '🗺 Project Roadmap'),
        synthesis.roadmap_items && synthesis.roadmap_items.length
          ? createEl('ul', { style: { margin: 0, paddingLeft: '16px', color: '#8b949e', fontSize: '12px' } },
              synthesis.roadmap_items.slice(0, 4).map(function(item, i) {
                return createEl('li', { key: i, style: { marginBottom: '4px' } }, item);
              })
            )
          : createEl('p', { style: { color: '#8b949e', fontSize: '12px' } }, 'No roadmap found')
      ),
      // Stats card
      createEl('div', { style: { backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '8px', padding: '12px' } },
        createEl('h4', { style: { color: '#00ff9f', margin: '0 0 8px', fontSize: '13px' } }, '📊 Project Stats'),
        createEl('p', { style: { fontSize: '12px', color: '#8b949e', margin: '4px 0' } }, '⭐ Stars: ' + (ghMeta.stars || 'N/A')),
        createEl('p', { style: { fontSize: '12px', color: '#8b949e', margin: '4px 0' } }, '🍴 Forks: ' + (ghMeta.forks || 'N/A')),
        createEl('p', { style: { fontSize: '12px', color: '#8b949e', margin: '4px 0' } }, '🐛 Open issues: ' + (ghMeta.open_issues_count || 'N/A')),
        createEl('p', { style: { fontSize: '12px', color: '#8b949e', margin: '4px 0' } }, '🔤 Language: ' + (ghMeta.language || 'N/A')),
        synthesis.maturity ? createEl('p', { style: { fontSize: '12px', color: '#8b949e', margin: '4px 0' } }, '📈 Maturity: ' + synthesis.maturity) : null,
        synthesis.contribution_style ? createEl('p', { style: { fontSize: '12px', color: '#8b949e', margin: '4px 0' } }, '🤝 Contrib style: ' + synthesis.contribution_style) : null
      )
    );

    var recs = data.recommendations && data.recommendations.length > 0 ? data.recommendations : null;
    var header = createEl('div', { style: { marginBottom: '20px', borderBottom: '1px solid #30363d', paddingBottom: '16px' } },
      createEl('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
        createEl('div', null,
          createEl('p', { style: { margin: '0 0 4px', color: '#8b949e' } }, 'Repo: ' + data.repo_slug),
          createEl('h2', { style: { margin: 0, color: '#e6edf3' } }, data.intelligence_summary.project_name || 'Project Review')
        ),
        createEl('div', { style: { textAlign: 'right' } },
          createEl('div', { style: { marginBottom: '8px' } },
            createEl('button', { onClick: approveSelected, disabled: submitting, style: { marginRight: '8px', backgroundColor: '#00ff9f', color: '#0d1117', border: 'none', padding: '10px 16px', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' } }, 'Approve selected'),
            createEl('button', { onClick: executeApproved, disabled: submitting, style: { backgroundColor: '#21262d', color: '#c9d1d9', border: '1px solid #30363d', padding: '10px 16px', borderRadius: '6px', fontWeight: 'bold', cursor: 'pointer' } }, 'Execute approved')
          )
        )
      ),
      message ? createEl('p', { style: { color: '#00ff9f', marginTop: '12px', fontSize: '14px' } }, '✓ ' + message) : null
    );

    var contentChildren = [ intelPanel, header ];
    if (recs) {
      contentChildren.push(createEl('div', { key: 'recs' }, recs.map(function (r, i) {
        var id = getRecId(r, i);
        var opp = r.opportunity || {};
        var spec = r.spec || {};
        var approved = approvedIds.indexOf(id) !== -1;

        function ScoreBar(label, value, color) {
          var pct = Math.round(((value || 0) / 10) * 100);
          return createEl('div', { style: { marginBottom: '6px' } },
            createEl('div', { style: { display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#8b949e' } },
              createEl('span', null, label),
              createEl('span', null, (value || 0).toFixed(1) + '/10')
            ),
            createEl('div', { style: { height: '4px', backgroundColor: '#30363d', borderRadius: '2px', marginTop: '2px' } },
              createEl('div', { style: { width: pct + '%', height: '100%', backgroundColor: color, borderRadius: '2px' } })
            )
          );
        }

        var typeColors = { feature: '#00b4d8', bug_fix: '#f85149', docs: '#8b949e',
          test: '#f0a500', refactor: '#a371f7', perf: '#00ff9f', security: '#ff7043' };
        var typeBadge = createEl('span', {
          style: { backgroundColor: typeColors[opp.type] || '#30363d', color: '#0d1117',
                   padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: 'bold',
                   marginRight: '8px' }
        }, opp.type || 'unknown');

        var compositeScore = opp.composite_score || r.quality_score || 0;

        return createEl('div', {
          key: id,
          style: { backgroundColor: '#0f1720', padding: '16px', marginBottom: '12px',
                   borderRadius: '8px', border: approved ? '2px solid #00ff9f' : '1px solid #30363d' }
        },
          // Header row
          createEl('label', { style: { display: 'flex', alignItems: 'flex-start', gap: '10px', cursor: 'pointer', marginBottom: '10px' } },
            createEl('input', { type: 'checkbox', checked: approved,
              onChange: function () { toggleApproval(id); }, style: { marginTop: '3px', flexShrink: 0 } }),
            createEl('div', { style: { flex: 1 } },
              createEl('div', { style: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '6px', marginBottom: '4px' } },
                typeBadge,
                createEl('strong', { style: { color: '#e6edf3' } }, opp.title || 'Recommendation ' + (i + 1)),
                createEl('span', { style: { color: '#00ff9f', fontSize: '12px', marginLeft: 'auto' } },
                  '★ ' + compositeScore.toFixed(2) + ' composite')
              ),
              opp.description ? createEl('p', { style: { color: '#8b949e', fontSize: '13px', margin: '0 0 8px' } }, opp.description) : null
            )
          ),

          // Score bars
          createEl('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 20px', marginBottom: '10px' } },
            ScoreBar('Impact', opp.impact_score, '#00ff9f'),
            ScoreBar('Novelty', opp.novelty_score, '#00b4d8'),
            ScoreBar('Visibility', opp.visibility_score, '#f0a500'),
            ScoreBar('Difficulty', opp.difficulty_score, '#f85149')
          ),

          // Evidence
          (function() {
            var ev = [];
            if (opp.evidence && opp.evidence.github_issues) {
              ev.push(createEl('span', { key: 'gh' }, '🐙 Issues: ' + opp.evidence.github_issues.slice(0, 2).join(' • ')));
            }
            if (opp.evidence && opp.evidence.strategic_goal) {
              ev.push(createEl('span', { key: 'strat', style: { color: '#f0a500' } }, '🎯 Strategic Priority: ' + opp.evidence.strategic_goal.toUpperCase()));
            }
            if (opp.evidence && opp.evidence.community_mentions) {
              ev.push(createEl('span', { key: 'comm' }, '💬 Community: ' + opp.evidence.community_mentions[0]));
            }
            
            return ev.length ? createEl('div', { style: { fontSize: '12px', color: '#8b949e', marginBottom: '8px', display: 'flex', gap: '12px' } },
                createEl('strong', null, 'Evidence: '),
                ev
              ) : null;
          })(),

          // Effort estimate
          createEl('div', { style: { display: 'flex', gap: '16px', fontSize: '12px', color: '#8b949e', marginBottom: '10px' } },
            createEl('span', null, '⏱ ~' + (opp.estimated_hours || '?') + 'h'),
            spec.files_to_create && spec.files_to_create.length
              ? createEl('span', null, '📄 ' + spec.files_to_create.length + ' new files') : null,
            spec.files_to_modify && spec.files_to_modify.length
              ? createEl('span', null, '✏️ ' + spec.files_to_modify.length + ' modified') : null
          ),

          // Resume talking point — the star feature
          spec.resume_talking_point ? createEl('div', {
            style: { backgroundColor: '#161b22', border: '1px solid #30363d', borderRadius: '6px',
                     padding: '8px 12px', marginBottom: '10px', fontSize: '13px' }
          },
            createEl('span', { style: { color: '#f0a500' } }, '📋 Resume: '),
            createEl('em', { style: { color: '#c9d1d9' } }, spec.resume_talking_point)
          ) : null,

          // Expandable: implementation plan
          spec.implementation_plan && spec.implementation_plan.length
            ? createEl('details', { style: { marginTop: '4px' } },
                createEl('summary', { style: { cursor: 'pointer', color: '#00b4d8', fontSize: '13px' } }, 'View implementation plan'),
                createEl('ol', { style: { paddingLeft: '20px', color: '#8b949e', fontSize: '13px', marginTop: '6px' } },
                  spec.implementation_plan.map(function (step, si) {
                    return createEl('li', { key: si, style: { marginBottom: '4px' } }, step);
                  })
                )
              )
            : null
        );
      })));
    } else {
      contentChildren.push(createEl('p', null, 'No recommendations.'));
    }

    return Card('Review — ' + jobId, createEl.apply(null, ['div', null].concat(contentChildren)));
  }

  function ResumeView() {
    var _a = useState(null), data = _a[0], setData = _a[1];
    var _b = useState(true), loading = _b[0], setLoading = _b[1];
    var _c = useState(null), error = _c[0], setError = _c[1];

    useEffect(function () {
      setLoading(true);
      fetchAPI('/resume').then(function (r) { setData(r); }).catch(function (e) { setError(e.message); }).finally(function () { setLoading(false); });
    }, []);

    if (loading) return Card(null, createEl('div', { style: { color: '#8b949e' } }, 'Loading resume...'));
    if (error) return Card('Error', createEl('div', null, error));
    if (!data) return Card('Resume', createEl('div', null, 'No resume bullets available.'));

    return Card('Resume', createEl('div', null,
      createEl('p', null, 'Successful PR bullets from completed jobs:'),
      createEl('ul', null, (data.resume_bullets || []).map(function (bullet, idx) {
        return createEl('li', { key: idx, style: { marginBottom: '8px' } }, bullet);
      }))
    ));
  }

  function NotFound() {
    return Card(null, createEl('div', { style: { color: '#f85149' } }, '404 - Page not found'));
  }

  function AppRouter() {
    var _a = useState(window.location.hash || '#/'), route = _a[0], setRoute = _a[1];
    useEffect(function () {
      function onHash() { setRoute(window.location.hash || '#/'); }
      window.addEventListener('hashchange', onHash);
      return function () { window.removeEventListener('hashchange', onHash); };
    }, []);

    var content = null;
    if (route.indexOf('#/job/') === 0) {
      var parts = route.slice(6).split('/');
      var jobId = parts[0];
      if (parts[1] === 'review') {
        content = createEl(ReviewView, { jobId: jobId });
      } else {
        content = createEl(JobView, { jobId: jobId });
      }
    } else if (route === '#/' || route === '' || route === '#/jobs') {
      content = createEl(Home, null);
    } else if (route === '#/resume') {
      content = createEl(ResumeView, null);
    } else {
      content = createEl(NotFound, null);
    }

    return createEl(Layout, null, content);
  }

  // Mount
  var root = document.getElementById('root');
  ReactDOM.createRoot(root).render(React.createElement(AppRouter));
})();
