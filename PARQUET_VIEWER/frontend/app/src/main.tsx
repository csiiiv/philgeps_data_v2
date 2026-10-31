import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import App from './App';
import './app.css';

// One-time compat: older shared links used query-string routing
// (?view=schema&q=…&process=…&search=…). Redirect them to the equivalent
// hash route (#/schema?q=…) before the router mounts. Full page reload
// happens once (the query string must be dropped), then never again.
const legacy = new URLSearchParams(window.location.search);
const legacyKeys = ['view', 'q', 'process', 'search'];
if (!window.location.hash && legacyKeys.some((k) => legacy.has(k))) {
  const view = legacy.get('view') ?? 'search';
  const path = view === 'search' ? '/' : `/${view}`;
  const rest = new URLSearchParams();
  for (const k of ['q', 'process', 'search']) {
    const v = legacy.get(k);
    if (v != null) rest.set(k, v);
  }
  const qs = rest.toString();
  window.location.replace(
    `${window.location.origin}${window.location.pathname}#${path}${qs ? `?${qs}` : ''}`,
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </StrictMode>,
);
