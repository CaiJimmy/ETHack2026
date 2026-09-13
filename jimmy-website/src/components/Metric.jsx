import React from 'react';

export function Metric({ label, value, unit }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}{unit ? <small>{unit}</small> : null}</strong>
    </div>
  );
}
