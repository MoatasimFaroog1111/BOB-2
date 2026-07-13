import React, { useEffect, useState } from "react";
import axios from "axios";

function JournalView() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchEntries = async () => {
    setLoading(true);
    setError("");

    try {
      const response = await axios.get(
        "http://localhost:8000/journal/entries"
      );

      setEntries(Array.isArray(response.data) ? response.data : []);
    } catch (err) {
      console.error("Failed to fetch journal entries:", err);
      setError("تعذر تحميل القيود المحاسبية من السيرفر.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEntries();
  }, []);

  const formatAmount = (value) => {
    const number = Number(value || 0);

    return number.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

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

      {!loading && !error && entries.length === 0 && (
        <p>
          لا توجد قيود حتى الآن. ارفع فاتورة أولًا، ثم اضغط زر
          <strong> Refresh</strong>.
        </p>
      )}

      {entries.map((entry, entryIndex) => (
        <div
          key={`${entry.reference || "entry"}-${entryIndex}`}
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

          <p>
            <strong>Memo:</strong> {entry.memo || "-"}
          </p>

          <p>
            <strong>Status:</strong> {entry.status || "draft"}
          </p>

          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              background: "#fff",
            }}
          >
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
                <tr key={lineIndex}>
                  <td style={cellStyle}>{line.account}</td>
                  <td style={numberCellStyle}>{formatAmount(line.debit)}</td>
                  <td style={numberCellStyle}>{formatAmount(line.credit)}</td>
                  <td style={cellStyle}>{line.description}</td>
                </tr>
              ))}

              <tr>
                <td style={totalCellStyle}>
                  <strong>Total</strong>
                </td>
                <td style={totalNumberCellStyle}>
                  <strong>
                    {formatAmount(
                      (entry.lines || []).reduce(
                        (sum, line) => sum + Number(line.debit || 0),
                        0
                      )
                    )}
                  </strong>
                </td>
                <td style={totalNumberCellStyle}>
                  <strong>
                    {formatAmount(
                      (entry.lines || []).reduce(
                        (sum, line) => sum + Number(line.credit || 0),
                        0
                      )
                    )}
                  </strong>
                </td>
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
