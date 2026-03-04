import React from 'react';

interface TablePreviewProps {
  preview: {
    headers: string[];
    rows: string[][];
    truncated: {
      rows: boolean;
      cols: boolean;
    };
  };
}

export function TablePreview({ preview }: TablePreviewProps) {
  return (
    <div style={{
      overflow: 'hidden',
      borderRadius: '4px',
      border: '1px solid #e2e8f0',
      backgroundColor: 'white'
    }}>
      <table style={{
        width: '100%',
        fontSize: '10px',
        fontFamily: 'monospace',
        borderCollapse: 'collapse'
      }}>
        <thead>
          <tr style={{ backgroundColor: '#f1f5f9' }}>
            {preview.headers.map((header, idx) => (
              <th
                key={idx}
                style={{
                  padding: '2px 4px',
                  textAlign: 'left',
                  color: '#475569',
                  fontWeight: 500,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  maxWidth: '60px'
                }}
                title={header}
              >
                {header}
              </th>
            ))}
            {preview.truncated.cols && (
              <th style={{ padding: '2px 4px', color: '#94a3b8' }}>…</th>
            )}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row, rowIdx) => (
            <tr
              key={rowIdx}
              style={{
                backgroundColor: rowIdx % 2 === 0 ? 'white' : '#f8fafc'
              }}
            >
              {row.map((cell, cellIdx) => (
                <td
                  key={cellIdx}
                  style={{
                    padding: '2px 4px',
                    color: '#334155',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: '60px'
                  }}
                  title={cell}
                >
                  {cell || '-'}
                </td>
              ))}
              {preview.truncated.cols && (
                <td style={{ padding: '2px 4px', color: '#94a3b8' }}>…</td>
              )}
            </tr>
          ))}
          {preview.truncated.rows && (
            <tr style={{ backgroundColor: '#f8fafc' }}>
              <td
                colSpan={preview.headers.length + (preview.truncated.cols ? 1 : 0)}
                style={{
                  padding: '2px 4px',
                  textAlign: 'center',
                  color: '#94a3b8'
                }}
              >
                …
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
