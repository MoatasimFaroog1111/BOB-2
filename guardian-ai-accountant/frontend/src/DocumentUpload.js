import React, { useState } from "react";
import axios from "axios";

function DocumentUpload() {
  const [file, setFile] = useState(null);
  const [response, setResponse] = useState(null);
  const [uploading, setUploading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    setUploading(true);
    try {
      const res = await axios.post(
        "http://localhost:8000/documents/upload",
        formData
      );
      setResponse(res.data);
    } catch (err) {
      alert("Upload failed");
      console.error(err);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ padding: "1rem" }}>
      <h2>📤 GuardianAI - Upload Document</h2>
      <input type="file" onChange={(e) => setFile(e.target.files[0])} />
      <button onClick={handleUpload} disabled={uploading}>
        {uploading ? "Uploading..." : "Upload"}
      </button>

      {response && (
        <div style={{ marginTop: "1rem" }}>
          <h3>📄 Document Type: {response.document_type}</h3>

          <h3>📊 Extracted Fields:</h3>
          <pre>{JSON.stringify(response.fields, null, 2)}</pre>

          {response.generated_journal && (
            <div>
              <h3>📘 Generated Journal Entry:</h3>
              <table
                border="1"
                cellPadding="8"
                style={{ borderCollapse: "collapse" }}
              >
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
              <table
                border="1"
                cellPadding="8"
                style={{ borderCollapse: "collapse" }}
              >
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Debit</th>
                    <th>Credit</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {response.generated_journal.lines.map((line, index) => (
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
          <pre
            style={{
              whiteSpace: "pre-wrap",
              background: "#eee",
              padding: "1rem",
            }}
          >
            {response.extracted_text || "No text extracted."}
          </pre>
        </div>
      )}
    </div>
  );
}

export default DocumentUpload;
