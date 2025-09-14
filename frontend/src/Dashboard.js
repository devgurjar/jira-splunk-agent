import React, { useEffect, useState, useMemo } from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  Container,
  Box,
  CircularProgress,
  Alert,
  TextField,
  InputAdornment,
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
  Link
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import SearchIcon from '@mui/icons-material/Search';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';

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

export default function Dashboard() {
  const API_BASE = process.env.REACT_APP_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000`;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('errors'); // errors | service | program

  useEffect(() => {
    let isMounted = true;
    async function fetchData() {
      setLoading(true);
      setError('');
      try {
        const res = await fetch(`${API_BASE}/report-data`);
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
  }, [API_BASE]);

  const summaryRows = useMemo(() => Array.isArray(data?.svc_rows) ? data.svc_rows : [], [data]);
  const reportItemsRaw = useMemo(() => Array.isArray(data?.report_items) ? data.report_items : [], [data]);

  const { reportItems, totals } = useMemo(() => {
    const q = query.trim().toLowerCase();
    let items = reportItemsRaw.filter((it) => {
      if (!q) return true;
      const hay = `${it.aem_service || ''} ${it.program_name || ''}`.toLowerCase();
      return hay.includes(q);
    });
    if (sortBy === 'errors') items = items.slice().sort((a, b) => (b.error_count || 0) - (a.error_count || 0));
    if (sortBy === 'service') items = items.slice().sort((a, b) => String(a.aem_service).localeCompare(String(b.aem_service)));
    if (sortBy === 'program') items = items.slice().sort((a, b) => String(a.program_name || '').localeCompare(String(b.program_name || '')));
    const totalErrors = items.reduce((s, v) => s + (v.error_count || 0), 0);
    return { reportItems: items, totals: { services: items.length, errors: totalErrors } };
  }, [reportItemsRaw, query, sortBy]);

  const theme = useMemo(() => createTheme({
    palette: {
      mode: 'light',
      primary: { main: '#1565C0' },
      secondary: { main: '#00ACC1' },
      background: { default: '#f7f9fc' },
    },
    shape: { borderRadius: 10 },
    typography: {
      fontSize: 15, // base font size (slightly larger than default)
      h5: { fontSize: '1.35rem', fontWeight: 700 },
      h6: { fontSize: '1.15rem', fontWeight: 700 },
      subtitle1: { fontSize: '1rem', fontWeight: 600 },
      body1: { fontSize: '1rem' },
      body2: { fontSize: '0.95rem' },
      caption: { fontSize: '0.9rem' },
    },
  }), []);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ minHeight: '100vh' }}>
      <AppBar position="static" color="primary">
        <Toolbar>
          <Typography variant="h5" sx={{ flexGrow: 1 }}>
            Daily Forms Submit Errors Dashboard
          </Typography>
          <Typography variant="body1" sx={{ opacity: 0.9 }}>
            <strong>Range:</strong> {data?.earliest || '-'} → {data?.latest || '-'}
          </Typography>
        </Toolbar>
      </AppBar>

      <Container sx={{ py: 3 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'stretch', sm: 'center' }} justifyContent="space-between" sx={{ mb: 2 }}>
          <TextField
            size="small"
            placeholder="Filter by service or program..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              )
            }}
            sx={{ maxWidth: 360 }}
          />
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>Sort:</Typography>
            <Chip label="Errors" color={sortBy==='errors'?'primary':'default'} size="small" onClick={() => setSortBy('errors')} />
            <Chip label="Service" color={sortBy==='service'?'primary':'default'} size="small" onClick={() => setSortBy('service')} />
            <Chip label="Program" color={sortBy==='program'?'primary':'default'} size="small" onClick={() => setSortBy('program')} />
            <Divider flexItem orientation="vertical" sx={{ mx: 1 }} />
            <Chip label={`Services: ${totals.services || 0}`} size="small" />
            <Chip label={`Failures: ${totals.errors || 0}`} size="small" color="error" />
          </Stack>
        </Stack>
        {loading && (
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', py: 8 }}>
            <CircularProgress />
          </Box>
        )}
        {!loading && error && (
          <Alert severity="warning">{error} — run POST /report-refresh and reload.</Alert>
        )}

        {!loading && !error && (
          <Box>
            <Typography variant="h5" sx={{ mb: 1 }}>Summary</Typography>
            <TableContainer component={Paper} elevation={0} sx={{ border: '1px solid #e0e0e0', overflow: 'hidden' }}>
              <Table size="medium">
                <TableHead>
                  <TableRow sx={{ bgcolor: 'primary.main' }}>
                    <TableCell sx={{ color: '#fff', fontWeight: 700, fontSize: '0.95rem' }}>TenantID</TableCell>
                    <TableCell sx={{ color: '#fff', fontWeight: 700, fontSize: '0.95rem' }}>ProgramName</TableCell>
                    <TableCell sx={{ color: '#fff', fontWeight: 700, fontSize: '0.95rem' }} align="right">ErrorCount</TableCell>
                    <TableCell sx={{ color: '#fff', fontWeight: 700, fontSize: '0.95rem' }}>SKYSI</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {summaryRows.map((r) => (
                    <TableRow key={r.aem_service} hover>
                      <TableCell sx={{ fontSize: '0.95rem' }}>{r.aem_service}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }}>{r.program_name || '<unknown program name>'}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }} align="right">{r.error_count || 0}</TableCell>
                      <TableCell sx={{ fontSize: '0.95rem' }}>
                        {r.skysi_key && r.skysi_url ? (
                          <Link href={r.skysi_url} target="_blank" rel="noreferrer">{r.skysi_key}</Link>
                        ) : '-'}
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
                            {(pe.messages || []).slice(0, 10).map((m, mi) => (
                              <Box key={mi}>
                                <Typography variant="subtitle1" sx={{ color: 'text.secondary', mb: 0.5 }}>{`Message ${mi + 1}`}</Typography>
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
                                  {truncateLines(m, 20)}
                                </Box>
                                <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                                  <IconButton size="small" aria-label="copy" onClick={() => navigator.clipboard.writeText(m)}>
                                    <ContentCopyIcon fontSize="inherit" />
                                  </IconButton>
                                </Box>
                              </Box>
                            ))}
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


