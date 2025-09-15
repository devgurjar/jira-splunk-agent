import React, { useEffect, useState, useMemo } from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  Container,
  Box,
  Alert,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Chip,
  Stack,
  Divider,
  Link,
  Button,
  FormControl,
  Select,
  MenuItem
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import LightModeIcon from '@mui/icons-material/LightMode';
import AssessmentOutlinedIcon from '@mui/icons-material/AssessmentOutlined';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';
import AccessTimeOutlinedIcon from '@mui/icons-material/AccessTimeOutlined';
import OpenInNewOutlinedIcon from '@mui/icons-material/OpenInNewOutlined';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CalendarMonthOutlinedIcon from '@mui/icons-material/CalendarMonthOutlined';
import CssBaseline from '@mui/material/CssBaseline';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Grid from '@mui/material/Grid';
import Tooltip from '@mui/material/Tooltip';
import Avatar from '@mui/material/Avatar';
import Skeleton from '@mui/material/Skeleton';

function decodeBase64Path(path) {
  try {
    if (!path) return '';
    const marker = '/adobe/forms/af/submit/';
    const idx = path.indexOf(marker);
    if (idx === -1) return path;
    const base = path.substring(idx + marker.length).split('?')[0];
    let b64 = base.replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4 !== 0) b64 += '=';
    const decoded = atob(b64);
    return `${marker}${decoded}`;
  } catch (e) {
    return path;
  }
}

function truncateLines(text, maxLines = 20) {
  if (!text) return '';
  const lines = String(text).split('\n');
  return lines.length > maxLines ? lines.slice(0, maxLines).join('\n') + '\n...' : text;
}

function formatUSD(amount) {
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(amount || 0);
  } catch (e) {
    const n = Number(amount || 0);
    return `$${Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '0'}`;
  }
}

function getProgramFromAemService(aemService) {
  try {
    if (!aemService) return '';
    const match = String(aemService).match(/-p(\d+)-e/i);
    return match && match[1] ? match[1] : '';
  } catch (e) {
    return '';
  }
}

export default function Dashboard() {
  const API_BASE = process.env.REACT_APP_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000`;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const query = '';
  const [themeMode, setThemeMode] = useState('light'); // light | dark
  const [reportDate, setReportDate] = useState(''); // YYYY-MM-DD or '' for latest
  const [availableDates, setAvailableDates] = useState([]);

  useEffect(() => {
    let isMounted = true;
    async function fetchData() {
      setLoading(true);
      setError('');
      try {
        const url = reportDate ? `${API_BASE}/report-data?date=${encodeURIComponent(reportDate)}` : `${API_BASE}/report-data`;
        const res = await fetch(url);
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || `Failed to load cached report data (${res.status})`);
        }
        const json = await res.json();
        if (isMounted) setData(json);
      } catch (e) {
        if (isMounted) setError(e.message || 'Failed to load data');
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    fetchData();
    return () => { isMounted = false; };
  }, [API_BASE, reportDate]);

  useEffect(() => {
    let isMounted = true;
    async function fetchDates() {
      try {
        const res = await fetch(`${API_BASE}/report-dates`);
        if (!res.ok) return;
        const j = await res.json();
        if (isMounted) {
          const arr = Array.isArray(j?.dates) ? j.dates : [];
          setAvailableDates(arr);
          // Default to today's date if present and nothing chosen yet
          if (!reportDate && arr.length > 0) {
            const today = new Date().toISOString().slice(0,10);
            if (arr.includes(today)) setReportDate(today);
          }
        }
      } catch {}
    }
    fetchDates();
    return () => { isMounted = false; };
  }, [API_BASE, reportDate]);

  const summaryRows = useMemo(() => Array.isArray(data?.svc_rows) ? data.svc_rows : [], [data]);
  const reportItemsRaw = useMemo(() => Array.isArray(data?.report_items) ? data.report_items : [], [data]);
  const itemByService = useMemo(() => {
    const m = {};
    for (const it of reportItemsRaw) {
      if (it && it.aem_service) m[it.aem_service] = it;
    }
    return m;
  }, [reportItemsRaw]);

  const { reportItems, totals } = useMemo(() => {
    const q = query.trim().toLowerCase();
    let items = reportItemsRaw.filter((it) => {
      if (!q) return true;
      const hay = `${it.aem_service || ''} ${it.program_name || ''}`.toLowerCase();
      return hay.includes(q);
    });
    items = items.slice().sort((a, b) => (b.error_count || 0) - (a.error_count || 0));
    const totalErrors = items.reduce((s, v) => s + (v.error_count || 0), 0);
    return { reportItems: items, totals: { services: items.length, errors: totalErrors } };
  }, [reportItemsRaw, query]);

  const revenueLoss = useMemo(() => (totals?.errors || 0) * 4, [totals?.errors]);

  const istDateTime = useMemo(() => {
    const iso = data?.generated_at;
    if (!iso) return { date: '-', time: '-' };
    try {
      const d = new Date(iso);
      const options = { timeZone: 'Asia/Kolkata', hour12: false };
      const date = d.toLocaleDateString('en-IN', { ...options, year: 'numeric', month: '2-digit', day: '2-digit' });
      const time = d.toLocaleTimeString('en-IN', { ...options, hour: '2-digit', minute: '2-digit', second: '2-digit' });
      return { date, time };
    } catch (e) {
      return { date: iso, time: '' };
    }
  }, [data?.generated_at]);

  const theme = useMemo(() => createTheme({
    palette: {
      mode: themeMode,
      primary: { main: themeMode === 'light' ? '#2563EB' : '#60A5FA' },
      secondary: { main: themeMode === 'light' ? '#0EA5E9' : '#67E8F9' },
      background: themeMode === 'light'
        ? { default: '#f7f9fc', paper: '#ffffff' }
        : { default: '#0b1220', paper: '#111827' },
    },
    shape: { borderRadius: 12 },
    typography: {
      fontSize: 15,
      h5: { fontSize: '1.35rem', fontWeight: 700 },
      h6: { fontSize: '1.15rem', fontWeight: 700 },
      subtitle1: { fontSize: '1rem', fontWeight: 600 },
      body1: { fontSize: '1rem' },
      body2: { fontSize: '0.95rem' },
      caption: { fontSize: '0.9rem' },
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            border: '1px solid',
            borderColor: themeMode === 'light' ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.08)'
          }
        }
      }
    }
  }), [themeMode]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ minHeight: '100vh', background: themeMode === 'light' ? 'linear-gradient(180deg, #f7f9fc 0%, #eef2f7 100%)' : 'linear-gradient(180deg, #0b1220 0%, #0f172a 100%)' }}>
      <AppBar position="static" color="transparent" elevation={0} sx={{
        background: 'linear-gradient(90deg, #0EA5E9 0%, #2563EB 50%, #7C3AED 100%)'
      }}>
        <Toolbar>
          <Typography variant="h5" sx={{ flexGrow: 1 }}>
            Daily Forms Submit Errors Dashboard
          </Typography>
          <Typography variant="body1" sx={{ opacity: 0.9, mr: 1 }}>
            <strong>Range:</strong> {data?.earliest || '-'} → {data?.latest || '-'}
          </Typography>
          <IconButton color="inherit" size="small" onClick={() => setThemeMode((m) => (m === 'light' ? 'dark' : 'light'))} aria-label="Toggle theme">
            {themeMode === 'light' ? <DarkModeIcon fontSize="small" /> : <LightModeIcon fontSize="small" />}
          </IconButton>
        </Toolbar>
      </AppBar>

      <Container sx={{ py: 3 }}>
        {/* Top filters and counters removed per request */}
        {loading && (
          <Box>
            <Grid container spacing={2} sx={{ mb: 2 }}>
              {[1,2,3].map((k) => (
                <Grid item xs={12} sm={4} md={3} key={k}>
                  <Card elevation={0}>
                    <CardContent>
                      <Stack direction="row" spacing={2} alignItems="center">
                        <Skeleton variant="circular" width={40} height={40} />
                        <Box sx={{ flex: 1 }}>
                          <Skeleton variant="text" width={90} />
                          <Skeleton variant="text" width={60} />
                        </Box>
                      </Stack>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
            <Grid container spacing={2} sx={{ mb: 2 }}>
              <Grid item xs={12} sm={6} md={4}>
                <FormControl fullWidth size="small" sx={{
                  '& .MuiOutlinedInput-root': {
                    bgcolor: (t) => t.palette.mode === 'light' ? '#fff' : 'rgba(255,255,255,0.06)',
                    borderRadius: 999,
                  },
                  '& .MuiOutlinedInput-notchedOutline': {
                    borderColor: (t) => t.palette.divider
                  },
                  '&:hover .MuiOutlinedInput-notchedOutline': {
                    borderColor: (t) => t.palette.primary.main
                  }
                }}>
                  <Select
                    id="report-date-select"
                    value={reportDate}
                    onChange={(e) => setReportDate(e.target.value)}
                    displayEmpty
                    disabled
                    renderValue={(value) => {
                      const label = value ? value : 'Loading report dates…';
                      return (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <CalendarMonthOutlinedIcon sx={{ fontSize: 18, color: 'text.secondary' }} />
                          <span>{label}</span>
                        </Box>
                      );
                    }}
                    MenuProps={{ PaperProps: { sx: { maxHeight: 360, borderRadius: 2 } } }}
                  >
                    <MenuItem value=""><em>Latest</em></MenuItem>
                    {availableDates.map((d) => (
                      <MenuItem key={d} value={d}>{d}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
            <Card elevation={0}>
              <CardContent>
                <Skeleton variant="rectangular" height={280} />
              </CardContent>
            </Card>
          </Box>
        )}
        {!loading && error && (
          <Alert severity="warning">{error} — run POST /report-refresh and reload.</Alert>
        )}

        {!loading && !error && (
          <Box>
            {/* Revenue impact alert removed per request */}
            <Grid container spacing={2} sx={{ mb: 2 }}>
              <Grid item xs={12} sm={4} md={2}>
                <Card elevation={0}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Avatar sx={{ bgcolor: 'primary.main' }}>
                        <AssessmentOutlinedIcon htmlColor="#fff" />
                      </Avatar>
                      <Box>
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Services</Typography>
                        <Typography variant="h6">{totals.services || 0}</Typography>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={4} md={2}>
                <Card elevation={0}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Avatar sx={{ bgcolor: 'warning.main' }}>
                        <WarningAmberOutlinedIcon htmlColor="#fff" />
                      </Avatar>
                      <Box>
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Potential loss</Typography>
                        <Typography variant="h6">{formatUSD(revenueLoss)}</Typography>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={4} md={2}>
                <Card elevation={0}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Avatar sx={{ bgcolor: 'error.main' }}>
                        <WarningAmberOutlinedIcon htmlColor="#fff" />
                      </Avatar>
                      <Box>
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Failures</Typography>
                        <Typography variant="h6">{totals.errors || 0}</Typography>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={4} md={2}>
                <Card elevation={0}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Avatar sx={{ bgcolor: 'secondary.main' }}>
                        <AccessTimeOutlinedIcon htmlColor="#fff" />
                      </Avatar>
                      <Box>
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Last generated</Typography>
                        <Tooltip title={data?.generated_at || '-'}>
                          <Typography variant="h6" noWrap sx={{ maxWidth: 220 }}>{`${istDateTime.date} • ${istDateTime.time}`}</Typography>
                        </Tooltip>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={8} md={4}>
                <Card elevation={0}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Avatar sx={{ bgcolor: 'secondary.main' }}>
                        <CalendarMonthOutlinedIcon htmlColor="#fff" />
                      </Avatar>
                      <Box sx={{ flex: 1 }}>
                        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Report date</Typography>
                        <FormControl size="small" fullWidth>
                          <Select
                            id="report-date-select"
                            value={reportDate}
                            onChange={(e) => setReportDate(e.target.value)}
                            displayEmpty
                            renderValue={(value) => (value ? value : 'Latest')}
                            MenuProps={{ PaperProps: { sx: { maxHeight: 360, borderRadius: 2 } } }}
                            sx={{
                              mt: 0.5,
                              '& .MuiOutlinedInput-notchedOutline': { borderColor: (t) => t.palette.divider },
                              '& .MuiSelect-select': { py: 0.5 }
                            }}
                          >
                            <MenuItem value=""><em>Latest</em></MenuItem>
                            {availableDates.map((d) => (
                              <MenuItem key={d} value={d}>{d}</MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>
            {/* Removed duplicate dropdown below metrics row */}
            <Box sx={{ mb: 1, display: 'flex', justifyContent: 'flex-end' }}>
              <Stack direction="row" spacing={1}>
                <Button
                  component="a"
                  href="https://splunk.or1.adobe.net/en-US/app/TA-aem_skyline/form_cs_product_error_dashboard?form.aem_envType=prod&form.programID=*&form.timePeriod.earliest=-24h%40h&form.timePeriod.latest=now&form.namespace=*&form.programEnvironment=*&form.aem_tier=publish"
                  target="_blank"
                  rel="noreferrer"
                  variant="outlined"
                  color="secondary"
                  size="small"
                  sx={{ textTransform: 'none', px: 1.5, py: 0.25 }}
                  endIcon={<OpenInNewOutlinedIcon fontSize="small" />}
                >
                  For detailed analysis, visit this dashboard
                </Button>
                <Button
                  component="a"
                  href="https://wiki.corp.adobe.com/display/lc/AEM+Forms+Submission+Errors+Analysis+rotary"
                  target="_blank"
                  rel="noreferrer"
                  variant="outlined"
                  color="info"
                  size="small"
                  sx={{ textTransform: 'none', px: 1.5, py: 0.25 }}
                  endIcon={<OpenInNewOutlinedIcon fontSize="small" />}
                >
                  Go to this wiki for rotary and insights
                </Button>
              </Stack>
            </Box>
            <Typography variant="h5" sx={{ mb: 1 }}>Summary</Typography>
            <TableContainer component={Paper} elevation={0} sx={{ border: '1px solid', borderColor: (t) => t.palette.divider }}>
              <Table size="medium">
                <TableHead>
                  <TableRow sx={{
                    background: (t) => t.palette.mode === 'light'
                      ? 'linear-gradient(90deg, #E0F2FE 0%, #DBEAFE 60%, #EDE9FE 100%)'
                      : 'linear-gradient(90deg, #0EA5E9 0%, #2563EB 60%, #7C3AED 100%)'
                  }}>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }}>TenantID</TableCell>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }}>ProgramName</TableCell>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }} align="right">ErrorCount</TableCell>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }} align="right">TotalSubmissions</TableCell>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }} align="right">Failure%</TableCell>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }}>SKYSI</TableCell>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }}>AEM CS Workspace</TableCell>
                    <TableCell sx={{ color: (t) => t.palette.mode === 'light' ? t.palette.text.primary : '#fff', fontWeight: 800, fontSize: '0.95rem' }} align="center">Action</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {summaryRows.map((r) => (
                    <TableRow key={r.aem_service} hover sx={{ '&:nth-of-type(odd)': { bgcolor: 'action.hover' } }}>
                      <TableCell sx={{ fontSize: '0.95rem' }}>{r.aem_service}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }}>{r.program_name || '<unknown program name>'}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }} align="right">{r.error_count || 0}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }} align="right">{(() => {
                        const ri = itemByService[r.aem_service] || {};
                        const v = Number.isFinite(Number(r.total_form_submissions)) ? Number(r.total_form_submissions) : Number(ri.total_form_submissions || 0);
                        return v;
                      })()}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }} align="right">{(() => {
                        const ri = itemByService[r.aem_service] || {};
                        const v = Number.isFinite(Number(r.failure_rate_pct)) ? Number(r.failure_rate_pct) : Number(ri.failure_rate_pct);
                        return Number.isFinite(v) ? `${v}%` : '-';
                      })()}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }}>
                        {r.skysi_key && r.skysi_url ? (
                          <Link href={r.skysi_url} target="_blank" rel="noreferrer">{r.skysi_key}</Link>
                        ) : '-'}
                      </TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }}>
                        {(() => {
                          const program = getProgramFromAemService(r.aem_service);
                          const href = program ? `https://aemcs-workspace.adobe.com/customer/program/${program}#environments` : '';
                          return href ? (
                            <Button component="a" href={href} target="_blank" rel="noreferrer" variant="outlined" size="small" sx={{ textTransform: 'none', px: 1.5, py: 0.25 }}>Tenant View</Button>
                          ) : '-';
                        })()}
                      </TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }} align="center">
                        <Button variant="outlined" color="primary" size="small" disabled aria-label={`Create ticket for ${r.aem_service}`} sx={{ textTransform: 'none', px: 1.5, py: 0.25 }}>Create Ticket</Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <Divider sx={{ my: 3 }} />

            <Typography variant="h5" sx={{ mb: 1 }}>Services</Typography>
            <Stack spacing={2}>
              {reportItems.map((item) => (
                <Accordion key={item.aem_service} defaultExpanded={false} disableGutters>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                        {`Service: ${item.aem_service}`}
                      </Typography>
                      <Chip label={`Program: ${item.program_name || '<unknown program name>'}`} size="medium" color="info" />
                      <Chip label={`Failures: ${item.error_count || 0}`} size="medium" color="error" />
                    </Box>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Stack spacing={2}>
                      {(item.paths || []).slice(0, 10).map((pe, idx) => (
                        <Paper key={`${item.aem_service}-${idx}`} variant="outlined" sx={{ p: 1.5 }}>
                          <Stack spacing={1}>
                            <Chip label={`Path`} size="medium" sx={{ bgcolor: '#1976d2', color: '#fff', width: 'fit-content' }} />
                            <Typography variant="body1" sx={{ fontWeight: 700 }}>
                              {decodeBase64Path(pe.path)}
                            </Typography>
                            {pe.time && (
                              <Typography variant="body2" sx={{ color: 'text.secondary' }}>Time: {pe.time}</Typography>
                            )}
                            <Divider />
                            {(pe.messages || []).length === 0 && (
                              <Typography variant="body1" color="error">&lt;no messages&gt;</Typography>
                            )}
                            {(pe.messages || []).slice(0, 10).map((m, mi) => {
                              const text = typeof m === 'string' ? m : (m?.msg || '');
                              const when = typeof m === 'object' ? (m?.time || '') : '';
                              return (
                              <Box key={mi}>
                                <Typography variant="subtitle1" sx={{ color: 'text.secondary', mb: 0.5 }}>{`Message ${mi + 1}${when ? ` — ${when}` : ''}`}</Typography>
                                <Box component="pre" sx={{
                                  m: 0,
                                  p: 1,
                                  bgcolor: '#ECEFF1',
                                  border: '1px solid #B0BEC5',
                                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                                  whiteSpace: 'pre-wrap',
                                  wordBreak: 'break-word',
                                  fontSize: 13.5,
                                  lineHeight: 1.4,
                                }}>
                                  {truncateLines(text, 20)}
                                </Box>
                                <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                                  <IconButton size="small" aria-label="copy" onClick={() => navigator.clipboard.writeText(text)}>
                                    <ContentCopyIcon fontSize="inherit" />
                                  </IconButton>
                                </Box>
                              </Box>
                            )})}
                          </Stack>
                        </Paper>
                      ))}
                    </Stack>
                  </AccordionDetails>
                </Accordion>
              ))}
            </Stack>

            <Box sx={{ mt: 4, color: 'text.secondary' }}>
              <Typography variant="caption">Last generated: {data?.generated_at || '-'}</Typography>
            </Box>
          </Box>
        )}
      </Container>
    </Box>
    </ThemeProvider>
  );
}


