import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  return (
    <main className="application-shell">
      <p className="eyebrow">Asset reconciliation</p>
      <h1>Application foundation is ready.</h1>
      <p>
        This presentation shell will display reconciliation data supplied by the
        API in later delivery tasks.
      </p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
