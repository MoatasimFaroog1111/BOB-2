import React, { useState } from "react";
import axios from "axios";

const API_BASE_URL = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

function getAccessToken() {
  return sessionStorage.getItem("access_token") || localStorage.getItem("access_token");
}

function DocumentUpload() {
  const [file, setFile] = useState(null);
  const [response, setResponse] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const handleUpload = async () => {
    if (!file) return;
    if (!API_BASE_URL) {
      setError("REACT_APP_API_URL is not configured.");
      return;
    }

    const accessToken = getAccessToken();
    if (!accessToken) {
      setError("Please sign in before uploading financial documents.");
      return;
    }

    const formData = new FormData();
    formData.append("files", file);

    setUploading(true);
    setError("");
    try {
      const res = await axios.post(
        `${API_BASE_URL}/api/v1/erp/upload-documents`,
        formData,
        {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      const firstResult = res.data?.results?.[0];
      setResponse(firstResult?.result || firstResult || res.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ padding: "1rem" }}>
      <h2>📤 GuardianAI - Upload Document</h2>
      <input
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv,.tsv,.xlsx,.ofx,.qfx,.qif,.mt940,.sta"
        onChange={(event) => setFile(event.target.files?.[0] || null)}
      />
      <button onClick={handleUpload} disabled={uploading || !file}>
        {uploading ? "Uploading..." : "Upload"}
      </button>

      {error && <p role="alert">{error}</p>}

      {response && (
        <div style={{ marginTop: "1rem" }}>
          <h3>📄 Document Type: {response.document_type || response.document_class || "Unknown"}</h3>
          <h3>📊 Extracted Fields:</h3>
          <pre>{JSON.stringify(response.fields || response, null, 2)}</pre>

          {response.generated_journal && (
            <div>
              <h3>📘 Generated Journal Entry:</h3>
              <table border="1" cellPadding="8" style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Reference</th>
                    <th>Memo</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{response.generated_journal.date}</td>
                    <td>{response.generated_journal.reference}</td>
                    <td>{response.generated_journal.memo}</td>
                    <td>{response.generated_journal.status}</td>
                  </tr>
                </tbody>
              </table>

              <h4 style={{ marginTop: "1rem" }}>🔢 Journal Lines:</h4>
              <table border="1" cellPadding="8" style={{ borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Debit</th>
                    <th>Credit</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {(response.generated_journal.lines || []).map((line, index) => (
                    <tr key={index}>
                      <td>{line.account}</td>
                      <td>{Number(line.debit || 0).toFixed(2)}</td>
                      <td>{Number(line.credit || 0).toFixed(2)}</td>
                      <td>{line.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>📝 OCR Output:</h3>
          <pre style={{ whiteSpace: "pre-wrap", background: "#eee", padding: "1rem" }}>
            {response.extracted_text || "No text extracted."}
          </pre>
        </div>
      )}
    </div>
  );
}

export default DocumentUpload;
