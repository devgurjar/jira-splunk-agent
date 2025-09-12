import React, { useState, useMemo, useEffect } from 'react';
import {
  Container, Box, Typography, TextField, Button, Card, CardContent, CircularProgress, Alert, Link, Divider, Stepper, Step, StepLabel, FormControlLabel, Checkbox
} from '@mui/material';
import BugReportIcon from '@mui/icons-material/BugReport';
import SearchIcon from '@mui/icons-material/Search';
import { LocalizationProvider, DateTimePicker } from '@mui/x-date-pickers';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { format, toZonedTime } from 'date-fns-tz';

const steps = ['Fetch SKYSI Jira', 'Analyze Splunk Logs', 'Create Forms Jira'];

function toISTBackendFormat(date) {
  if (!date) return null;
  // Convert to IST
  const istDate = toZonedTime(date, 'Asia/Kolkata');
  // Format as MM/DD/YYYY:HH:mm:ss
  return format(istDate, 'MM/dd/yyyy:HH:mm:ss', { timeZone: 'Asia/Kolkata' });
}

function App() {
  const [aemService, setAemService] = useState('');
  const [jiraResult, setJiraResult] = useState(null);
  const [aemFields, setAemFields] = useState(null);
  const [splunkResult, setSplunkResult] = useState(null);
  const [formsJiraKey, setFormsJiraKey] = useState(null);
  const [loadingStep, setLoadingStep] = useState(-1); // -1: idle, 0: fetching Jira, 1: Splunk, 2: Forms Jira
  const [error, setError] = useState('');
  const [earliest, setEarliest] = useState(null);
  const [latest, setLatest] = useState(null);
  const [useLastDay, setUseLastDay] = useState(true);

  function computeLastOneDayRange() {
    const now = new Date();
    const todayMidnight = new Date(now);
    todayMidnight.setHours(0, 0, 0, 0);
    const yesterdayMidnight = new Date(todayMidnight);
    yesterdayMidnight.setDate(yesterdayMidnight.getDate() - 1);
    return { start: yesterdayMidnight, end: todayMidnight };
  }

  useEffect(() => {
    if (useLastDay) {
      const { start, end } = computeLastOneDayRange();
      setEarliest(start);
      setLatest(end);
    }
  }, [useLastDay]);

  function decodeBase64Path(path) {
    try {
      if (!path) return '';
      const marker = '/adobe/forms/af/submit/';
      const idx = path.indexOf(marker);
      if (idx === -1) return path;
      const base = path.substring(idx + marker.length).split('?')[0];
      // Base64 URL-safe normalization
      let b64 = base.replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4 !== 0) b64 += '=';
      const decoded = atob(b64);
      return `${marker}${decoded}`;
    } catch (e) {
      return path;
    }
  }

  // Compute unique Splunk messages grouped by path (dedup within each path)
  const messagesByPath = useMemo(() => {
    const grouped = new Map();
    if (!splunkResult || !splunkResult.length) return [];
    for (const r of splunkResult) {
      const rawPath = (r?.path || 'Unknown path').trim();
      const path = decodeBase64Path(rawPath);
      const msg = (r?.msg || '').trim();
      const time = r?.orig_time || r?._time || r?.event_time || '';
      if (!msg) continue;
      if (!grouped.has(path)) grouped.set(path, { seen: new Set(), items: [] });
      const bucket = grouped.get(path);
      if (!bucket.seen.has(msg)) {
        bucket.seen.add(msg);
        bucket.items.push({ msg, time });
      }
    }
    return Array.from(grouped.entries()).map(([path, { items }]) => ({ path, items }));
  }, [splunkResult]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoadingStep(0);
    setJiraResult(null);
    setAemFields(null);
    setSplunkResult(null);
    setFormsJiraKey(null);
    setError('');
    try {
      // Step 1: find SKYSI ticket(s) by aem_service
      const findRes = await fetch('http://localhost:8000/find-skysi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ aem_service: aemService })
      });
      if (!findRes.ok) {
        const err = await findRes.json();
        setError(err.error || 'Failed to search SKYSI by aem_service');
        setLoadingStep(-1);
        return;
      }
      const findData = await findRes.json();
      const issues = (findData && findData.issues) || [];
      if (!issues.length) {
        setError('No open SKYSI ticket found for the provided aem_service.');
        setLoadingStep(-1);
        return;
      }
      // Show the found Jira summary immediately
      setJiraResult(findData);
      setLoadingStep(1);

      // Step 2: run the existing process with the first matching SKYSI key
      const selectedKey = issues[0].key;
      const res = await fetch('http://localhost:8000/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jira_id: selectedKey,
          earliest: toISTBackendFormat(useLastDay ? computeLastOneDayRange().start : earliest),
          latest: toISTBackendFormat(useLastDay ? computeLastOneDayRange().end : latest)
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        setError(err.error || 'Unknown error');
        setLoadingStep(-1);
        return;
      }
      const data = await res.json();
      setAemFields(data.aem_fields);
      // Progressive append of Splunk results to avoid long wait feeling
      const results = Array.isArray(data.splunk_result) ? data.splunk_result : [];
      setSplunkResult([]);
      results.forEach((item, idx) => {
        setTimeout(() => {
          setSplunkResult(prev => [...(prev || []), item]);
          if (idx === results.length - 1) {
            setLoadingStep(2);
            setTimeout(() => {
              setFormsJiraKey(data.forms_jira_key);
              setLoadingStep(-1);
            }, 800);
          }
        }, 150 * idx);
      });
    } catch (err) {
      setError('Failed to connect to backend.');
      setLoadingStep(-1);
    }
  };

  // Helper to set time to 00:00 if user only picks a date
  function handleDateTimeChange(setter) {
    return (date) => {
      if (!date) {
        setter(null);
        return;
      }
      // If the time is not set (i.e., user picked a date from calendar, not time), set to 00:00
      // MUI DateTimePicker always sets a time, so we check if minutes/seconds are 0 and if the time is close to now (default behavior)
      const d = new Date(date);
      if (
        d.getHours() === new Date().getHours() &&
        d.getMinutes() === new Date().getMinutes() &&
        d.getSeconds() === new Date().getSeconds()
      ) {
        d.setHours(0, 0, 0, 0);
        setter(d);
      } else {
        setter(d);
      }
    };
  }

  const renderJiraSummary = () => {
    if (!jiraResult?.issues?.length) return null;
    const issue = jiraResult.issues[0];
    const fields = issue.fields || {};
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            SKYSI Jira: <Link href={`https://jira.corp.adobe.com/browse/${issue.key}`} target="_blank" rel="noopener">{issue.key}</Link>
          </Typography>
          <Typography variant="subtitle1" color="text.secondary">{fields.summary}</Typography>
          <Divider sx={{ my: 1 }} />
          {messagesByPath.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" gutterBottom>Unique Splunk Error Messages by Path</Typography>
              {messagesByPath.map((group, gIdx) => (
                <Box key={gIdx} sx={{ mb: 2 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700, mb: 1 }}>{group.path}</Typography>
                  <Box component="ul" sx={{ pl: 2, mb: 0 }}>
                    {group.items.map((e, idx) => (
                      <li key={idx}>
                        {e.time && (
                          <Typography variant="caption" color="text.secondary">{e.time}</Typography>
                        )}
                        <Box sx={{ bgcolor: '#f5f5f5', p: 1, borderRadius: 1, fontFamily: 'monospace', fontSize: 14, whiteSpace: 'pre-line', mb: 1 }}>
                          {e.msg}
                        </Box>
                      </li>
                    ))}
                  </Box>
                </Box>
              ))}
            </Box>
          )}
        </CardContent>
      </Card>
    );
  };

  const renderAemFields = () => {
    if (!aemFields) return null;
    return (
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>AEM Extracted Fields</Typography>
          <Box component="ul" sx={{ pl: 2, mb: 0 }}>
            {Object.entries(aemFields).map(([k, v]) => (
              <li key={k}><b>{k}:</b> {String(v)}</li>
            ))}
          </Box>
        </CardContent>
      </Card>
    );
  };

  const renderSplunkError = () => {
    if (!splunkResult || !splunkResult.length) return null;
    const first = splunkResult[0];
    // Show only first 10 lines of error message
    const errorLines = (first.msg || '').split('\n').slice(0, 10).join('\n');
    return (
      <Card sx={{ mb: 2, bgcolor: '#fff3e0' }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>First Splunk Error Message (First 10 lines)</Typography>
          <Typography variant="caption" color="text.secondary">
            {first.orig_time || first._time || first.event_time || ''}
          </Typography>
          <Box sx={{ bgcolor: '#f5f5f5', p: 2, mt: 1, borderRadius: 1, fontFamily: 'monospace', fontSize: 14, whiteSpace: 'pre-line' }}>
            {errorLines}
          </Box>
        </CardContent>
      </Card>
    );
  };

  const renderFormsJira = () => {
    if (!formsJiraKey) return null;
    return (
      <Card sx={{ mb: 2, borderLeft: '5px solid #1976d2' }}>
        <CardContent>
          <Typography variant="h6" color="primary" gutterBottom>
            <BugReportIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
            New Forms Jira Created
          </Typography>
          <Typography variant="body1">
            <Link href={`https://jira.corp.adobe.com/browse/${formsJiraKey}`} target="_blank" rel="noopener">
              {formsJiraKey}
            </Link>
          </Typography>
        </CardContent>
      </Card>
    );
  };

  return (
    <Container maxWidth="md" sx={{ py: 6 }}>
      <Box sx={{ textAlign: 'center', mb: 4 }}>
        <Typography variant="h4" fontWeight={700} gutterBottom>
          Create AEM Forms Jira from SKYSI Jira
        </Typography>
        <Typography variant="subtitle1" color="text.secondary">
          Enter a SKYSI Jira ID to extract context, analyze Splunk logs, and create a new Forms Jira with all details and error context.
        </Typography>
      </Box>
      <LocalizationProvider dateAdapter={AdapterDateFns}>
        <Box component="form" onSubmit={handleSubmit} sx={{ display: 'flex', gap: 2, mb: 4, alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap' }}>
          <TextField
            label="AEM Service"
            value={aemService}
            onChange={e => setAemService(e.target.value)}
            required
            size="small"
            sx={{ minWidth: 260 }}
            disabled={loadingStep !== -1}
            placeholder="e.g., cm-p115977-e1164724"
          />
          <DateTimePicker
            label="Earliest (optional)"
            value={earliest}
            onChange={handleDateTimeChange(setEarliest)}
            renderInput={(params) => <TextField {...params} size="small" sx={{ minWidth: 220 }} />}
            disabled={loadingStep !== -1 || useLastDay}
          />
          <DateTimePicker
            label="Latest (optional)"
            value={latest}
            onChange={handleDateTimeChange(setLatest)}
            renderInput={(params) => <TextField {...params} size="small" sx={{ minWidth: 220 }} />}
            disabled={loadingStep !== -1 || useLastDay}
          />
          <FormControlLabel
            control={<Checkbox checked={useLastDay} onChange={(e) => setUseLastDay(e.target.checked)} />}
            label="Last 1 day (12:00 AM to 12:00 AM)"
          />
          <Button type="submit" variant="contained" size="large" startIcon={<SearchIcon />} disabled={loadingStep !== -1}>
            {loadingStep !== -1 ? <CircularProgress size={24} /> : 'Create Jira'}
          </Button>
        </Box>
      </LocalizationProvider>
      <Stepper activeStep={
        formsJiraKey ? 3 :
        splunkResult ? 2 :
        jiraResult ? 1 : 0
      } alternativeLabel sx={{ mb: 4 }}>
        {steps.map((label, idx) => (
          <Step key={label} completed={
            (idx === 0 && jiraResult) ||
            (idx === 1 && splunkResult) ||
            (idx === 2 && formsJiraKey)
          }>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {jiraResult && renderJiraSummary()}
      {aemFields && renderAemFields()}
      {loadingStep === 1 && (
        <Box sx={{ textAlign: 'center', my: 4 }}><CircularProgress size={40} /><Typography sx={{ mt: 2 }}>Analyzing Splunk logs...</Typography></Box>
      )}
      {/* {splunkResult && splunkResult.length > 0 && renderSplunkError()} */}
      {splunkResult && splunkResult.length === 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>There is no submit failure error for the specified time range.</Alert>
      )}
      {loadingStep === 2 && splunkResult && splunkResult.length > 0 && (
        <Box sx={{ textAlign: 'center', my: 4 }}><CircularProgress size={40} /><Typography sx={{ mt: 2 }}>Creating Forms Jira...</Typography></Box>
      )}
      {formsJiraKey && splunkResult && splunkResult.length > 0 && renderFormsJira()}
      {splunkResult && splunkResult.length > 0 && !formsJiraKey && (
        <Alert severity="warning" sx={{ mb: 2 }}>Splunk errors were found, but the Forms Jira was not created. Please check backend logs.</Alert>
      )}
    </Container>
  );
}

export default App;
