import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import { clearAstronoteLoadCaches } from './model/workspaceCache'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary
      fallbackTitle="The workspace failed to load."
      recoverLabel="Clear cache and reload"
      onRecover={() => {
        clearAstronoteLoadCaches();
        window.location.reload();
      }}
    >
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
