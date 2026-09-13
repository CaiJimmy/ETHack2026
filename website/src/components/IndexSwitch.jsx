import React from 'react';

const OPTIONS = [
  { id: 'paris', label: 'Paris index' },
  { id: 'ours', label: 'Our index' }
];

export function IndexSwitch({ index = 'ours', setIndex }) {
  return (
    <div className="index-switch" role="group" aria-label="Index">
      {OPTIONS.map(o => (
        <button
          key={o.id}
          type="button"
          aria-pressed={index === o.id}
          className={index === o.id ? 'active' : ''}
          onClick={() => setIndex && setIndex(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
