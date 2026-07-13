import React, { useEffect, useState } from "react";
import axios from "axios";

const API_BASE_URL = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

function getAccessToken() {
  return sessionStorage.getItem("access_token");
}

function JournalView() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchEntries = async () => {
    setLoading(true);
    setError("");

    if (!API_BASE_URL) {
      setError("REACT_APP_API_URL is not configured.");
      setLoading(false);
      return;
    }

    const accessToken = getAccessToken();
    if (!accessToken) {
      setError("يجب تسجيل الدخول قبل عرض القيود المحاسبية.");
      setLoading(false);
      return;
    }

    try {
      const response = await axios.get(
        `${API_BASE_URL}/api/v1/journal/entries`,
        {
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }
      );
      setEntries(Array.isArray(response.data) ? response.data : []);
    } catch (err) {
      setError(err.response?.data?.detail || "تعذر تحميل القيود المحاسبية من السيرفر.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEntries();
  }, []);

  const formatAmount = (value) =>
    Number(value || 0).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "1rem",
        }}
      >
        <h2>📘 Journal Entries</h2>
        <button
          type="button"
          onClick={fetchEntries}
          disabled={loading}
          style={{
            padding: "8px 16px",
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          style={{
            background: "#fee",
            border: "1px solid #d99",
            padding: "1rem",
            marginBottom: "1rem",
          }}
        >
          {error}
        </div>
      )}

      {!loading && !error && entries.length === 0 && <p>لا توجد قيود حتى الآن.</p>}

      {entries.map((entry) => (
        <div
          key={entry.id}
          style={{
            marginBottom: "2rem",
            border: "1px solid #ccc",
            borderRadius: "8px",
            padding: "1rem",
            background: "#fafafa",
          }}
        >
          <h3>
            {entry.reference || "No Reference"} — {entry.date || "No Date"}
          </h3>
          <p><strong>Memo:</strong> {entry.memo || "-"}</p>
          <p><strong>Status:</strong> {entry.status || "draft"}</p>

          <table style={{ width: "100%", borderCollapse: "collapse", background: "#fff" }}>
            <thead>
              <tr>
                <th style={headerStyle}>Account</th>
                <th style={headerStyle}>Debit</th>
                <th style={headerStyle}>Credit</th>
                <th style={headerStyle}>Description</th>
              </tr>
            </thead>
            <tbody>
              {(entry.lines || []).map((line, lineIndex) => (
                <tr key={`${entry.id}-${lineIndex}`}>
                  <td style={cellStyle}>{line.account}</td>
                  <td style={numberCellStyle}>{formatAmount(line.debit)}</td>
                  <td style={numberCellStyle}>{formatAmount(line.credit)}</td>
                  <td style={cellStyle}>{line.description}</td>
                </tr>
              ))}
              <tr>
                <td style={totalCellStyle}><strong>Total</strong></td>
                <td style={totalNumberCellStyle}><strong>{formatAmount(entry.total_debit)}</strong></td>
                <td style={totalNumberCellStyle}><strong>{formatAmount(entry.total_credit)}</strong></td>
                <td style={totalCellStyle}></td>
              </tr>
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

const headerStyle = {
  border: "1px solid #ccc",
  padding: "10px",
  textAlign: "left",
  background: "#eee",
};

const cellStyle = {
  border: "1px solid #ccc",
  padding: "10px",
};

const numberCellStyle = {
  ...cellStyle,
  textAlign: "right",
};

const totalCellStyle = {
  ...cellStyle,
  background: "#f0f0f0",
};

const totalNumberCellStyle = {
  ...totalCellStyle,
  textAlign: "right",
};

export default JournalView;
