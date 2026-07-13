import React from "react";
import DocumentUpload from "./DocumentUpload";
import JournalView from "./JournalView";

function App() {
  return (
    <div
      style={{
        maxWidth: "1200px",
        margin: "0 auto",
        padding: "2rem",
        fontFamily: "Arial, sans-serif",
      }}
    >
      <h1>🤖 GuardianAI Accountant</h1>

      <DocumentUpload />

      <hr style={{ margin: "3rem 0" }} />

      <JournalView />
    </div>
  );
}

export default App;
