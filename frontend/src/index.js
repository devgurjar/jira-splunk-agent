import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import Dashboard from './Dashboard';
import DailyGraph from './DailyGraph';
import reportWebVitals from './reportWebVitals';

const root = ReactDOM.createRoot(document.getElementById('root'));
const path = window.location.pathname;
const showGraph = window.location.search.includes('view=graph');
function TopBanner() {
  const goDash = () => {
    const u = new URL(window.location.href);
    u.searchParams.delete('view');
    window.location.href = u.toString();
  };
  const goGraph = () => {
    const u = new URL(window.location.href);
    u.searchParams.set('view', 'graph');
    window.location.href = u.toString();
  };
  const isGraph = showGraph;
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 1000,
      background: 'linear-gradient(90deg, #0EA5E9 0%, #2563EB 50%, #7C3AED 100%)',
      boxShadow: '0 2px 10px rgba(0,0,0,0.12)'
    }}>
      <div style={{
        maxWidth: 1200, margin: '0 auto', padding: '10px 16px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            fontWeight: 800, letterSpacing: 0.3,
            color: '#fff', fontSize: 18
          }}>Forms Submit Insights</div>
        </div>
        <div style={{
          background: 'rgba(255,255,255,0.18)',
          padding: 4, borderRadius: 999, display: 'flex', gap: 6
        }}>
          <button onClick={goDash} style={{
            padding: '6px 12px', borderRadius: 999,
            border: '1px solid transparent',
            background: isGraph ? 'transparent' : '#fff',
            color: isGraph ? '#fff' : '#1f2937',
            fontWeight: 600, cursor: 'pointer', minWidth: 110
          }}>Dashboard</button>
          <button onClick={goGraph} style={{
            padding: '6px 12px', borderRadius: 999,
            border: '1px solid transparent',
            background: !isGraph ? 'transparent' : '#fff',
            color: !isGraph ? '#fff' : '#1f2937',
            fontWeight: 600, cursor: 'pointer', minWidth: 110
          }}>Daily Graph</button>
        </div>
      </div>
    </div>
  );
}
root.render(
  <React.StrictMode>
    <TopBanner />
    {showGraph ? <DailyGraph /> : (path === '/dashboard' ? <Dashboard /> : <App />)}
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
